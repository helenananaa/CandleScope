#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub struct Span {
    pub start: usize,
    pub end: usize,
}

impl Span {
    #[must_use]
    pub const fn new(start: usize, end: usize) -> Self {
        Self { start, end }
    }

    #[must_use]
    pub fn merge(self, other: Self) -> Self {
        Self {
            start: self.start.min(other.start),
            end: self.end.max(other.end),
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct LineCol {
    pub line: usize,
    pub column: usize,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SourceFile {
    name: String,
    text: String,
    line_starts: Vec<usize>,
}

impl SourceFile {
    #[must_use]
    pub fn new(name: impl Into<String>, text: impl Into<String>) -> Self {
        let text = text.into();
        let mut line_starts = vec![0];
        for (index, byte) in text.bytes().enumerate() {
            if byte == b'\n' {
                line_starts.push(index + 1);
            }
        }

        Self {
            name: name.into(),
            text,
            line_starts,
        }
    }

    #[must_use]
    pub fn name(&self) -> &str {
        &self.name
    }

    #[must_use]
    pub fn text(&self) -> &str {
        &self.text
    }

    #[must_use]
    pub fn span_text(&self, span: Span) -> Option<&str> {
        self.text.get(span.start..span.end)
    }

    #[must_use]
    pub fn line_col(&self, offset: usize) -> LineCol {
        let line_index = match self.line_starts.binary_search(&offset) {
            Ok(index) => index,
            Err(index) => index.saturating_sub(1),
        };
        let line_start = self.line_starts[line_index];
        let column = self.text.get(line_start..offset).map_or_else(
            || offset.saturating_sub(line_start),
            |prefix| prefix.chars().count(),
        ) + 1;

        LineCol {
            line: line_index + 1,
            column,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn maps_offsets_to_line_columns() {
        let source = SourceFile::new("test.pine", "one\ntwo\n");

        assert_eq!(source.line_col(0), LineCol { line: 1, column: 1 });
        assert_eq!(source.line_col(4), LineCol { line: 2, column: 1 });
        assert_eq!(source.line_col(6), LineCol { line: 2, column: 3 });
    }

    #[test]
    fn maps_utf8_offsets_to_character_columns() {
        let source = SourceFile::new("test.pine", "éx\nαβ\n");

        assert_eq!(source.line_col(0), LineCol { line: 1, column: 1 });
        assert_eq!(source.line_col("é".len()), LineCol { line: 1, column: 2 });
        assert_eq!(
            source.line_col("éx\nα".len()),
            LineCol { line: 2, column: 2 }
        );
    }
}
