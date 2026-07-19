use crate::{Diagnostic, SourceFile, Span};

const MAX_STRING_CHARS: usize = 40_960;

#[derive(Debug, Clone, PartialEq)]
pub struct Token {
    pub kind: TokenKind,
    pub span: Span,
}

#[derive(Debug, Clone, PartialEq)]
pub enum TokenKind {
    Eof,
    Newline,
    VersionDirective(u16),
    Identifier(String),
    Int(i64),
    Float(f64),
    String(String),
    ColorHex(String),
    True,
    False,
    If,
    Else,
    Indent,
    Dedent,
    For,
    Switch,
    While,
    Break,
    Continue,
    Import,
    To,
    By,
    Var,
    Varip,
    And,
    Or,
    Not,
    Plus,
    PlusEq,
    Minus,
    MinusEq,
    Star,
    StarEq,
    Slash,
    SlashEq,
    Percent,
    PercentEq,
    Eq,
    Arrow,
    ColonEq,
    EqEq,
    BangEq,
    Gt,
    Gte,
    Lt,
    Lte,
    Question,
    Colon,
    Dot,
    Comma,
    LParen,
    RParen,
    LBracket,
    RBracket,
}

#[derive(Debug, Clone, PartialEq)]
pub struct Lexed {
    pub tokens: Vec<Token>,
    pub diagnostics: Vec<Diagnostic>,
}

#[must_use]
pub fn lex(source: &SourceFile) -> Lexed {
    Lexer::new(source).lex()
}

struct Lexer<'a> {
    source: &'a SourceFile,
    text: &'a str,
    pos: usize,
    tokens: Vec<Token>,
    diagnostics: Vec<Diagnostic>,
    line_start: bool,
    indent_stack: Vec<usize>,
    paren_depth: usize,
    structured_layout_paren_depth: Option<usize>,
}

impl<'a> Lexer<'a> {
    fn new(source: &'a SourceFile) -> Self {
        Self {
            source,
            text: source.text(),
            pos: 0,
            tokens: Vec::new(),
            diagnostics: Vec::new(),
            line_start: true,
            indent_stack: vec![0],
            paren_depth: 0,
            structured_layout_paren_depth: None,
        }
    }

    fn lex(mut self) -> Lexed {
        while let Some(mut byte) = self.peek_byte() {
            if self.line_start {
                self.handle_line_start();
                let Some(next_byte) = self.peek_byte() else {
                    break;
                };
                byte = next_byte;
            }

            match byte {
                b' ' | b'\t' | b'\r' => {
                    self.pos += 1;
                }
                b'\n' if self.paren_depth > 0 && self.structured_layout_paren_depth.is_none() => {
                    self.pos += 1;
                    self.line_start = true;
                }
                b'\n' if self.starts_legacy_line_wrap() => {
                    self.pos += 1;
                    self.line_start = false;
                }
                b'\n' => {
                    self.single(TokenKind::Newline);
                    self.line_start = true;
                }
                b'0'..=b'9' => self.number(),
                b'a'..=b'z' | b'A'..=b'Z' | b'_' => self.identifier_or_keyword(),
                b'"' | b'\'' if self.starts_with_repeated(byte, 3) => {
                    self.multiline_string(byte);
                }
                b'"' | b'\'' => self.string(byte),
                b'#' => self.color_hex(),
                b'/' if self.peek_next() == Some(b'/') => self.comment_or_version(),
                b'+' if self.peek_next() == Some(b'=') => self.double(TokenKind::PlusEq),
                b'+' => self.single(TokenKind::Plus),
                b'-' if self.peek_next() == Some(b'=') => self.double(TokenKind::MinusEq),
                b'-' => self.single(TokenKind::Minus),
                b'*' if self.peek_next() == Some(b'=') => self.double(TokenKind::StarEq),
                b'*' => self.single(TokenKind::Star),
                b'/' if self.peek_next() == Some(b'=') => self.double(TokenKind::SlashEq),
                b'/' => self.single(TokenKind::Slash),
                b'%' if self.peek_next() == Some(b'=') => self.double(TokenKind::PercentEq),
                b'%' => self.single(TokenKind::Percent),
                b'=' if self.peek_next() == Some(b'=') => self.double(TokenKind::EqEq),
                b'=' if self.peek_next() == Some(b'>') => self.double(TokenKind::Arrow),
                b'=' => self.single(TokenKind::Eq),
                b':' if self.peek_next() == Some(b'=') => self.double(TokenKind::ColonEq),
                b':' => self.single(TokenKind::Colon),
                b'!' if self.peek_next() == Some(b'=') => self.double(TokenKind::BangEq),
                b'>' if self.peek_next() == Some(b'=') => self.double(TokenKind::Gte),
                b'>' => self.single(TokenKind::Gt),
                b'<' if self.peek_next() == Some(b'=') => self.double(TokenKind::Lte),
                b'<' => self.single(TokenKind::Lt),
                b'?' => self.single(TokenKind::Question),
                b'.' => self.single(TokenKind::Dot),
                b',' => self.single(TokenKind::Comma),
                b'(' => self.open_paren(),
                b')' => self.close_paren(),
                b'[' => self.single(TokenKind::LBracket),
                b']' => self.single(TokenKind::RBracket),
                _ => self.unexpected_byte(),
            }
        }

        self.close_indents();
        self.tokens.push(Token {
            kind: TokenKind::Eof,
            span: Span::new(self.pos, self.pos),
        });

        Lexed {
            tokens: self.tokens,
            diagnostics: self.diagnostics,
        }
    }

    fn peek_byte(&self) -> Option<u8> {
        self.text.as_bytes().get(self.pos).copied()
    }

    fn peek_next(&self) -> Option<u8> {
        self.text.as_bytes().get(self.pos + 1).copied()
    }

    fn starts_legacy_line_wrap(&self) -> bool {
        let bytes = self.text.as_bytes();
        let mut next = self.pos + 1;
        let mut indent = 0_usize;

        while let Some(byte) = bytes.get(next) {
            match byte {
                b' ' => indent += 1,
                b'\t' => indent += 4,
                _ => break,
            }
            next += 1;
        }

        let current_indent = *self
            .indent_stack
            .last()
            .expect("indent stack always contains root indent");
        indent > current_indent && !indent.is_multiple_of(4)
    }

    fn single(&mut self, kind: TokenKind) {
        let start = self.pos;
        self.pos += 1;
        if !matches!(kind, TokenKind::Newline) {
            self.line_start = false;
        }
        self.tokens.push(Token {
            kind,
            span: Span::new(start, self.pos),
        });
    }

    fn double(&mut self, kind: TokenKind) {
        let start = self.pos;
        self.pos += 2;
        self.line_start = false;
        self.tokens.push(Token {
            kind,
            span: Span::new(start, self.pos),
        });
    }

    fn open_paren(&mut self) {
        self.single(TokenKind::LParen);
        self.paren_depth += 1;
    }

    fn close_paren(&mut self) {
        self.single(TokenKind::RParen);
        if self
            .structured_layout_paren_depth
            .is_some_and(|depth| self.paren_depth <= depth)
        {
            self.structured_layout_paren_depth = None;
        }
        self.paren_depth = self.paren_depth.saturating_sub(1);
    }

    fn number(&mut self) {
        let start = self.pos;
        self.consume_while(|byte| byte.is_ascii_digit());

        let mut is_float = false;
        if self.peek_byte() == Some(b'.')
            && self
                .text
                .as_bytes()
                .get(self.pos + 1)
                .is_some_and(u8::is_ascii_digit)
        {
            is_float = true;
            self.pos += 1;
            self.consume_while(|byte| byte.is_ascii_digit());
        }
        if self.starts_valid_exponent() {
            is_float = true;
            self.pos += 1;
            if self
                .peek_byte()
                .is_some_and(|byte| matches!(byte, b'+' | b'-'))
            {
                self.pos += 1;
            }
            self.consume_while(|byte| byte.is_ascii_digit());
        }

        let raw = &self.text[start..self.pos];
        let kind = if is_float {
            match raw.parse::<f64>() {
                Ok(value) if value.is_finite() => TokenKind::Float(value),
                Ok(_) => {
                    self.diagnostics.push(Diagnostic::error(
                        "E_LEX_FLOAT",
                        "invalid float literal",
                        Span::new(start, self.pos),
                    ));
                    TokenKind::Float(0.0)
                }
                Err(_) => {
                    self.diagnostics.push(Diagnostic::error(
                        "E_LEX_FLOAT",
                        "invalid float literal",
                        Span::new(start, self.pos),
                    ));
                    TokenKind::Float(0.0)
                }
            }
        } else {
            match raw.parse::<i64>() {
                Ok(value) => TokenKind::Int(value),
                Err(_) => {
                    self.diagnostics.push(Diagnostic::error(
                        "E_LEX_INT",
                        "invalid integer literal",
                        Span::new(start, self.pos),
                    ));
                    TokenKind::Int(0)
                }
            }
        };

        self.tokens.push(Token {
            kind,
            span: Span::new(start, self.pos),
        });
        self.line_start = false;
    }

    fn starts_valid_exponent(&self) -> bool {
        if !self
            .peek_byte()
            .is_some_and(|byte| matches!(byte, b'e' | b'E'))
        {
            return false;
        }

        let bytes = self.text.as_bytes();
        let mut index = self.pos + 1;
        if bytes
            .get(index)
            .is_some_and(|byte| matches!(*byte, b'+' | b'-'))
        {
            index += 1;
        }

        bytes.get(index).is_some_and(u8::is_ascii_digit)
    }

    fn identifier_or_keyword(&mut self) {
        let start = self.pos;
        self.consume_while(|byte| byte.is_ascii_alphanumeric() || byte == b'_');
        let raw = &self.text[start..self.pos];
        let kind = match raw {
            "true" => TokenKind::True,
            "false" => TokenKind::False,
            "if" => TokenKind::If,
            "else" => TokenKind::Else,
            "for" => TokenKind::For,
            "switch" => TokenKind::Switch,
            "while" => TokenKind::While,
            "break" => TokenKind::Break,
            "continue" => TokenKind::Continue,
            "import" => TokenKind::Import,
            "to" => TokenKind::To,
            "by" => TokenKind::By,
            "var" => TokenKind::Var,
            "varip" => TokenKind::Varip,
            "and" => TokenKind::And,
            "or" => TokenKind::Or,
            "not" => TokenKind::Not,
            _ => TokenKind::Identifier(raw.to_owned()),
        };

        self.tokens.push(Token {
            kind,
            span: Span::new(start, self.pos),
        });
        self.line_start = false;
        if self.paren_depth > 0
            && matches!(raw, "if" | "for" | "switch" | "while")
            && self.structured_layout_paren_depth.is_none()
        {
            self.structured_layout_paren_depth = Some(self.paren_depth);
        }
    }

    fn string(&mut self, delimiter: u8) {
        let start = self.pos;
        self.pos += 1;
        let mut value = String::new();

        while let Some(byte) = self.peek_byte() {
            if byte == delimiter {
                self.pos += 1;
                self.finish_string(start, value);
                return;
            }

            match byte {
                b'\\' => self.string_escape(delimiter, &mut value),
                b'\r' | b'\n' => {
                    if !self.string_line_wrap(&mut value) {
                        self.diagnostics.push(Diagnostic::error(
                            "E_LEX_STRING",
                            "unterminated string literal",
                            Span::new(start, self.pos),
                        ));
                        return;
                    }
                }
                _ => {
                    // Consume a full UTF-8 scalar value rather than a single
                    // byte so multi-byte characters are preserved verbatim.
                    let ch = self.text[self.pos..].chars().next().unwrap_or('\u{FFFD}');
                    self.pos += ch.len_utf8();
                    value.push(ch);
                }
            }
        }

        self.diagnostics.push(Diagnostic::error(
            "E_LEX_STRING",
            "unterminated string literal",
            Span::new(start, self.pos),
        ));
    }

    fn multiline_string(&mut self, delimiter: u8) {
        let start = self.pos;
        self.pos += 3;
        let mut value = String::new();

        while let Some(byte) = self.peek_byte() {
            if self.starts_with_repeated(delimiter, 3) {
                self.pos += 3;
                self.finish_string(start, value);
                return;
            }

            match byte {
                b'\\' => self.string_escape(delimiter, &mut value),
                b'\r' => {
                    self.pos += 1;
                    if self.peek_byte() == Some(b'\n') {
                        self.pos += 1;
                    }
                    value.push('\n');
                }
                b'\n' => {
                    self.pos += 1;
                    value.push('\n');
                }
                _ => {
                    // Consume a full UTF-8 scalar value rather than a single
                    // byte so multi-byte characters are preserved verbatim.
                    let ch = self.text[self.pos..].chars().next().unwrap_or('\u{FFFD}');
                    self.pos += ch.len_utf8();
                    value.push(ch);
                }
            }
        }

        self.diagnostics.push(Diagnostic::error(
            "E_LEX_STRING",
            "unterminated multiline string literal",
            Span::new(start, self.pos),
        ));
    }

    fn finish_string(&mut self, start: usize, value: String) {
        let span = Span::new(start, self.pos);
        if value.chars().count() > MAX_STRING_CHARS {
            self.diagnostics.push(Diagnostic::error(
                "E_LEX_STRING_LIMIT",
                format!("string literal cannot exceed {MAX_STRING_CHARS} characters"),
                span,
            ));
        }
        self.tokens.push(Token {
            kind: TokenKind::String(value),
            span,
        });
        self.line_start = false;
    }

    fn string_line_wrap(&mut self, value: &mut String) -> bool {
        let bytes = self.text.as_bytes();
        let mut next = self.pos;

        if bytes.get(next) == Some(&b'\r') {
            next += 1;
            if bytes.get(next) == Some(&b'\n') {
                next += 1;
            }
        } else if bytes.get(next) == Some(&b'\n') {
            next += 1;
        } else {
            return false;
        }

        let indent_start = next;
        while bytes.get(next) == Some(&b' ') {
            next += 1;
        }
        if next == indent_start {
            return false;
        }

        self.pos = next;
        value.push(' ');
        true
    }

    fn string_escape(&mut self, delimiter: u8, value: &mut String) {
        self.pos += 1;
        match self.peek_byte() {
            Some(b'n') => {
                self.pos += 1;
                value.push('\n');
            }
            Some(b't') => {
                self.pos += 1;
                value.push('\t');
            }
            Some(b'r') => {
                self.pos += 1;
                value.push('\r');
            }
            Some(escaped) if escaped == delimiter => {
                self.pos += 1;
                value.push(char::from(delimiter));
            }
            Some(b'\\') => {
                self.pos += 1;
                value.push('\\');
            }
            Some(b'\r' | b'\n') => {
                // Leave physical line endings for `string` to validate as a
                // space-indented wrap instead of treating them as unknown
                // escaped characters.
            }
            Some(_) => {
                // Unknown escape: keep the escaped character literally,
                // consuming a full UTF-8 scalar value.
                let ch = self.text[self.pos..].chars().next().unwrap_or('\u{FFFD}');
                self.pos += ch.len_utf8();
                value.push(ch);
            }
            None => {}
        }
    }

    fn starts_with_repeated(&self, delimiter: u8, count: usize) -> bool {
        self.text
            .as_bytes()
            .get(self.pos..self.pos.saturating_add(count))
            .is_some_and(|bytes| bytes.iter().all(|byte| *byte == delimiter))
    }

    fn color_hex(&mut self) {
        let start = self.pos;
        self.pos += 1;
        self.consume_while(|byte| byte.is_ascii_hexdigit());
        let raw = &self.text[start..self.pos];

        if matches!(raw.len(), 7 | 9) {
            self.tokens.push(Token {
                kind: TokenKind::ColorHex(raw.to_owned()),
                span: Span::new(start, self.pos),
            });
            self.line_start = false;
        } else {
            self.diagnostics.push(Diagnostic::error(
                "E_LEX_COLOR",
                "expected color literal in #RRGGBB or #RRGGBBAA form",
                Span::new(start, self.pos),
            ));
        }
    }

    fn comment_or_version(&mut self) {
        let start = self.pos;
        let line_end = self.text[start..]
            .find('\n')
            .map_or(self.text.len(), |offset| start + offset);
        let line = &self.text[start..line_end];

        if let Some(raw_version) = line.strip_prefix("//@version=") {
            match raw_version.trim().parse::<u16>() {
                Ok(version) => self.tokens.push(Token {
                    kind: TokenKind::VersionDirective(version),
                    span: Span::new(start, line_end),
                }),
                Err(_) => self.diagnostics.push(Diagnostic::error(
                    "E_LEX_VERSION",
                    "invalid version directive",
                    Span::new(start, line_end),
                )),
            }
        }

        self.pos = line_end;
        self.line_start = false;
    }

    fn unexpected_byte(&mut self) {
        let start = self.pos;
        self.pos += 1;
        let line_col = self.source.line_col(start);
        self.diagnostics.push(Diagnostic::error(
            "E_LEX_CHAR",
            format!(
                "unexpected character at line {}, column {}",
                line_col.line, line_col.column
            ),
            Span::new(start, self.pos),
        ));
    }

    fn consume_while(&mut self, mut predicate: impl FnMut(u8) -> bool) {
        while self.peek_byte().is_some_and(&mut predicate) {
            self.pos += 1;
        }
    }

    fn handle_line_start(&mut self) {
        let start = self.pos;
        let mut indent = 0_usize;

        while let Some(byte) = self.peek_byte() {
            match byte {
                b' ' => {
                    indent += 1;
                    self.pos += 1;
                }
                b'\t' => {
                    indent += 4;
                    self.pos += 1;
                }
                b'\r' => {
                    self.pos += 1;
                }
                _ => break,
            }
        }

        if matches!(self.peek_byte(), Some(b'\n') | None) {
            return;
        }

        if self.peek_byte() == Some(b'/') && self.peek_next() == Some(b'/') {
            return;
        }

        if self.paren_depth > 0 && self.structured_layout_paren_depth.is_none() {
            self.line_start = false;
            return;
        }

        let current = *self
            .indent_stack
            .last()
            .expect("indent stack always contains root indent");
        if indent > current {
            self.indent_stack.push(indent);
            self.tokens.push(Token {
                kind: TokenKind::Indent,
                span: Span::new(start, self.pos),
            });
        } else if indent < current {
            while indent
                < *self
                    .indent_stack
                    .last()
                    .expect("indent stack always contains root indent")
            {
                self.indent_stack.pop();
                self.tokens.push(Token {
                    kind: TokenKind::Dedent,
                    span: Span::new(start, self.pos),
                });
            }

            if indent
                != *self
                    .indent_stack
                    .last()
                    .expect("indent stack always contains root indent")
            {
                self.diagnostics.push(Diagnostic::error(
                    "E_LEX_INDENT",
                    "inconsistent indentation",
                    Span::new(start, self.pos),
                ));
            }
        }

        self.line_start = false;
    }

    fn close_indents(&mut self) {
        while self.indent_stack.len() > 1 {
            self.indent_stack.pop();
            self.tokens.push(Token {
                kind: TokenKind::Dedent,
                span: Span::new(self.pos, self.pos),
            });
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn kinds(source: &str) -> Vec<TokenKind> {
        let source = SourceFile::new("test.pine", source);
        lex(&source)
            .tokens
            .into_iter()
            .map(|token| token.kind)
            .collect()
    }

    #[test]
    fn lexes_version_and_indicator_call() {
        assert_eq!(
            kinds("//@version=5\nindicator(\"Demo\", overlay=true)\n"),
            vec![
                TokenKind::VersionDirective(5),
                TokenKind::Newline,
                TokenKind::Identifier("indicator".to_owned()),
                TokenKind::LParen,
                TokenKind::String("Demo".to_owned()),
                TokenKind::Comma,
                TokenKind::Identifier("overlay".to_owned()),
                TokenKind::Eq,
                TokenKind::True,
                TokenKind::RParen,
                TokenKind::Newline,
                TokenKind::Eof,
            ]
        );
    }

    #[test]
    fn lexes_utf8_string_contents_and_unknown_escapes() {
        assert_eq!(
            kinds("label = \"中\\\\文\\好\\n\"\n"),
            vec![
                TokenKind::Identifier("label".to_owned()),
                TokenKind::Eq,
                TokenKind::String("中\\文好\n".to_owned()),
                TokenKind::Newline,
                TokenKind::Eof,
            ]
        );
    }

    #[test]
    fn lexes_single_quoted_strings_and_matching_delimiter_escapes() {
        assert_eq!(
            kinds("double = \"a'b\\\"c\"\nsingle = 'a\"b\\'c'\n"),
            vec![
                TokenKind::Identifier("double".to_owned()),
                TokenKind::Eq,
                TokenKind::String("a'b\"c".to_owned()),
                TokenKind::Newline,
                TokenKind::Identifier("single".to_owned()),
                TokenKind::Eq,
                TokenKind::String("a\"b'c".to_owned()),
                TokenKind::Newline,
                TokenKind::Eof,
            ]
        );
    }

    #[test]
    fn lexes_indented_single_line_string_wraps_as_one_space() {
        assert_eq!(
            kinds(concat!(
                "double = \"first\n second\n     中\"\n",
                "single = 'alpha\r\n  beta'\n",
                "bare_cr = \"left\r right\"\n",
            )),
            vec![
                TokenKind::Identifier("double".to_owned()),
                TokenKind::Eq,
                TokenKind::String("first second 中".to_owned()),
                TokenKind::Newline,
                TokenKind::Identifier("single".to_owned()),
                TokenKind::Eq,
                TokenKind::String("alpha beta".to_owned()),
                TokenKind::Newline,
                TokenKind::Identifier("bare_cr".to_owned()),
                TokenKind::Eq,
                TokenKind::String("left right".to_owned()),
                TokenKind::Newline,
                TokenKind::Eof,
            ]
        );
    }

    #[test]
    fn rejects_unindented_single_line_string_wrap_and_recovers() {
        for text in [
            "broken = \"first\nsecond\"\nafter = 1\n",
            "broken = \"first\\\nsecond\"\nafter = 1\n",
        ] {
            let source = SourceFile::new("test.pine", text);
            let lexed = lex(&source);

            assert!(lexed.diagnostics.iter().any(|diagnostic| {
                diagnostic.code == "E_LEX_STRING"
                    && diagnostic.message == "unterminated string literal"
            }));
            assert!(
                lexed
                    .tokens
                    .iter()
                    .any(|token| { token.kind == TokenKind::Identifier("after".to_owned()) })
            );
        }
    }

    #[test]
    fn enforces_decoded_string_literal_character_limit() {
        let at_limit = "界".repeat(MAX_STRING_CHARS);
        let accepted = SourceFile::new("test.pine", format!("value = \"{at_limit}\"\n"));
        let lexed = lex(&accepted);
        assert!(lexed.diagnostics.is_empty(), "{:?}", lexed.diagnostics);
        assert!(lexed.tokens.iter().any(|token| {
            matches!(&token.kind, TokenKind::String(value) if value == &at_limit)
        }));

        let escaped_at_limit = "\\n".repeat(MAX_STRING_CHARS);
        let accepted_escaped =
            SourceFile::new("test.pine", format!("value = \"{escaped_at_limit}\"\n"));
        let lexed = lex(&accepted_escaped);
        assert!(lexed.diagnostics.is_empty(), "{:?}", lexed.diagnostics);
        assert!(lexed.tokens.iter().any(|token| {
            matches!(&token.kind, TokenKind::String(value) if value.chars().count() == MAX_STRING_CHARS)
        }));

        for literal in [
            format!("'{}'", "x".repeat(MAX_STRING_CHARS + 1)),
            format!("\"\"\"{}\"\"\"", "x".repeat(MAX_STRING_CHARS + 1)),
        ] {
            let source = SourceFile::new("test.pine", format!("value = {literal}\nafter = 1\n"));
            let expected_start = source.text().find(&literal).expect("literal start");
            let expected_end = expected_start + literal.len();
            let lexed = lex(&source);
            let diagnostic = lexed
                .diagnostics
                .iter()
                .find(|diagnostic| diagnostic.code == "E_LEX_STRING_LIMIT")
                .expect("string limit diagnostic");

            assert_eq!(
                diagnostic.message,
                "string literal cannot exceed 40960 characters"
            );
            assert_eq!(diagnostic.span, Span::new(expected_start, expected_end));
            assert!(
                lexed
                    .tokens
                    .iter()
                    .any(|token| { token.kind == TokenKind::Identifier("after".to_owned()) })
            );
        }
    }

    #[test]
    fn lexes_compound_assignment_operators() {
        assert_eq!(
            kinds("a += 1\nb -= 2\nc *= 3\nd /= 4\ne %= 5\n"),
            vec![
                TokenKind::Identifier("a".to_owned()),
                TokenKind::PlusEq,
                TokenKind::Int(1),
                TokenKind::Newline,
                TokenKind::Identifier("b".to_owned()),
                TokenKind::MinusEq,
                TokenKind::Int(2),
                TokenKind::Newline,
                TokenKind::Identifier("c".to_owned()),
                TokenKind::StarEq,
                TokenKind::Int(3),
                TokenKind::Newline,
                TokenKind::Identifier("d".to_owned()),
                TokenKind::SlashEq,
                TokenKind::Int(4),
                TokenKind::Newline,
                TokenKind::Identifier("e".to_owned()),
                TokenKind::PercentEq,
                TokenKind::Int(5),
                TokenKind::Newline,
                TokenKind::Eof,
            ]
        );
    }

    #[test]
    fn reports_unterminated_single_quoted_string() {
        let source = SourceFile::new("test.pine", "value = 'unterminated\nnext = 1\n");
        let lexed = lex(&source);

        assert!(lexed.diagnostics.iter().any(|diagnostic| {
            diagnostic.code == "E_LEX_STRING" && diagnostic.message == "unterminated string literal"
        }));
        assert!(
            lexed
                .tokens
                .iter()
                .any(|token| { token.kind == TokenKind::Identifier("next".to_owned()) })
        );
    }

    #[test]
    fn lexes_multiline_strings_without_layout_tokens() {
        let source = concat!(
            "double = \"\"\"first\r\n  中 \" quote\"\"\"\n",
            "single = '''alpha\n\tbeta's text'''\n",
            "joined = \"\"\"a\"\"\" + '''b'''\n",
        );

        assert_eq!(
            kinds(source),
            vec![
                TokenKind::Identifier("double".to_owned()),
                TokenKind::Eq,
                TokenKind::String("first\n  中 \" quote".to_owned()),
                TokenKind::Newline,
                TokenKind::Identifier("single".to_owned()),
                TokenKind::Eq,
                TokenKind::String("alpha\n\tbeta's text".to_owned()),
                TokenKind::Newline,
                TokenKind::Identifier("joined".to_owned()),
                TokenKind::Eq,
                TokenKind::String("a".to_owned()),
                TokenKind::Plus,
                TokenKind::String("b".to_owned()),
                TokenKind::Newline,
                TokenKind::Eof,
            ]
        );
    }

    #[test]
    fn reports_unterminated_multiline_string_at_eof() {
        let source = SourceFile::new(
            "test.pine",
            "safe = 1\nbroken = \"\"\"unterminated\n  still content\n",
        );
        let expected_start = source.text().find("\"\"\"").expect("opening delimiter");
        let lexed = lex(&source);
        let diagnostic = lexed
            .diagnostics
            .iter()
            .find(|diagnostic| diagnostic.code == "E_LEX_STRING")
            .expect("unterminated multiline string diagnostic");

        assert_eq!(diagnostic.message, "unterminated multiline string literal");
        assert_eq!(
            diagnostic.span,
            Span::new(expected_start, source.text().len())
        );
        assert!(
            lexed
                .tokens
                .iter()
                .any(|token| { token.kind == TokenKind::Identifier("safe".to_owned()) })
        );
    }

    #[test]
    fn lexes_history_and_namespaces() {
        assert_eq!(
            kinds("x = ta.sma(close, 20)[1]\n"),
            vec![
                TokenKind::Identifier("x".to_owned()),
                TokenKind::Eq,
                TokenKind::Identifier("ta".to_owned()),
                TokenKind::Dot,
                TokenKind::Identifier("sma".to_owned()),
                TokenKind::LParen,
                TokenKind::Identifier("close".to_owned()),
                TokenKind::Comma,
                TokenKind::Int(20),
                TokenKind::RParen,
                TokenKind::LBracket,
                TokenKind::Int(1),
                TokenKind::RBracket,
                TokenKind::Newline,
                TokenKind::Eof,
            ]
        );
    }

    #[test]
    fn lexes_scientific_float_literals() {
        assert_eq!(
            kinds("a = 3e8\nb = 6.02E-23\nc = 1E+6\n"),
            vec![
                TokenKind::Identifier("a".to_owned()),
                TokenKind::Eq,
                TokenKind::Float(3e8),
                TokenKind::Newline,
                TokenKind::Identifier("b".to_owned()),
                TokenKind::Eq,
                TokenKind::Float(6.02E-23),
                TokenKind::Newline,
                TokenKind::Identifier("c".to_owned()),
                TokenKind::Eq,
                TokenKind::Float(1E+6),
                TokenKind::Newline,
                TokenKind::Eof,
            ]
        );
    }

    #[test]
    fn lexes_for_range_keywords() {
        assert_eq!(
            kinds("for i = 0 to 10 by 2\n"),
            vec![
                TokenKind::For,
                TokenKind::Identifier("i".to_owned()),
                TokenKind::Eq,
                TokenKind::Int(0),
                TokenKind::To,
                TokenKind::Int(10),
                TokenKind::By,
                TokenKind::Int(2),
                TokenKind::Newline,
                TokenKind::Eof,
            ]
        );
    }

    #[test]
    fn lexes_while_keyword() {
        assert_eq!(
            kinds("while close > open\n    break\n"),
            vec![
                TokenKind::While,
                TokenKind::Identifier("close".to_owned()),
                TokenKind::Gt,
                TokenKind::Identifier("open".to_owned()),
                TokenKind::Newline,
                TokenKind::Indent,
                TokenKind::Break,
                TokenKind::Newline,
                TokenKind::Dedent,
                TokenKind::Eof,
            ]
        );
    }

    #[test]
    fn lexes_switch_keyword() {
        assert_eq!(
            kinds("switch\n    close > open => high\n    => close\n"),
            vec![
                TokenKind::Switch,
                TokenKind::Newline,
                TokenKind::Indent,
                TokenKind::Identifier("close".to_owned()),
                TokenKind::Gt,
                TokenKind::Identifier("open".to_owned()),
                TokenKind::Arrow,
                TokenKind::Identifier("high".to_owned()),
                TokenKind::Newline,
                TokenKind::Arrow,
                TokenKind::Identifier("close".to_owned()),
                TokenKind::Newline,
                TokenKind::Dedent,
                TokenKind::Eof,
            ]
        );
    }

    #[test]
    fn lexes_loop_control_keywords() {
        assert_eq!(
            kinds("break\ncontinue\n"),
            vec![
                TokenKind::Break,
                TokenKind::Newline,
                TokenKind::Continue,
                TokenKind::Newline,
                TokenKind::Eof,
            ]
        );
    }

    #[test]
    fn lexes_indented_blocks() {
        assert_eq!(
            kinds("if close > open\n    plot(close)\nelse\n    plot(open)\n"),
            vec![
                TokenKind::If,
                TokenKind::Identifier("close".to_owned()),
                TokenKind::Gt,
                TokenKind::Identifier("open".to_owned()),
                TokenKind::Newline,
                TokenKind::Indent,
                TokenKind::Identifier("plot".to_owned()),
                TokenKind::LParen,
                TokenKind::Identifier("close".to_owned()),
                TokenKind::RParen,
                TokenKind::Newline,
                TokenKind::Dedent,
                TokenKind::Else,
                TokenKind::Newline,
                TokenKind::Indent,
                TokenKind::Identifier("plot".to_owned()),
                TokenKind::LParen,
                TokenKind::Identifier("open".to_owned()),
                TokenKind::RParen,
                TokenKind::Newline,
                TokenKind::Dedent,
                TokenKind::Eof,
            ]
        );
    }

    #[test]
    fn suppresses_layout_inside_parenthesized_line_wrapping() {
        assert_eq!(
            kinds(concat!(
                "value = (\n",
                "    1 + // comment\n",
                "0 + (\n",
                "        2\n",
                "    )\n",
                ")\n",
                "after = 3\n",
            )),
            vec![
                TokenKind::Identifier("value".to_owned()),
                TokenKind::Eq,
                TokenKind::LParen,
                TokenKind::Int(1),
                TokenKind::Plus,
                TokenKind::Int(0),
                TokenKind::Plus,
                TokenKind::LParen,
                TokenKind::Int(2),
                TokenKind::RParen,
                TokenKind::RParen,
                TokenKind::Newline,
                TokenKind::Identifier("after".to_owned()),
                TokenKind::Eq,
                TokenKind::Int(3),
                TokenKind::Newline,
                TokenKind::Eof,
            ]
        );
    }

    #[test]
    fn preserves_structured_block_layout_inside_parentheses() {
        assert_eq!(
            kinds(concat!(
                "value = plot(switch\n",
                "    true =>\n",
                "        1\n",
                ")\n",
                "after = (\n",
                "0\n",
                ")\n",
            )),
            vec![
                TokenKind::Identifier("value".to_owned()),
                TokenKind::Eq,
                TokenKind::Identifier("plot".to_owned()),
                TokenKind::LParen,
                TokenKind::Switch,
                TokenKind::Newline,
                TokenKind::Indent,
                TokenKind::True,
                TokenKind::Arrow,
                TokenKind::Newline,
                TokenKind::Indent,
                TokenKind::Int(1),
                TokenKind::Newline,
                TokenKind::Dedent,
                TokenKind::Dedent,
                TokenKind::RParen,
                TokenKind::Newline,
                TokenKind::Identifier("after".to_owned()),
                TokenKind::Eq,
                TokenKind::LParen,
                TokenKind::Int(0),
                TokenKind::RParen,
                TokenKind::Newline,
                TokenKind::Eof,
            ]
        );
    }

    #[test]
    fn suppresses_layout_for_legacy_line_wrapping() {
        assert_eq!(
            kinds(concat!(
                "value = open +\r\n",
                "  high + // comment\r\n",
                "      low +\n",
                " close\n",
                "if true\n",
                "    local = open +\n",
                "\t  close\n",
                "    plot(local)\n",
            )),
            vec![
                TokenKind::Identifier("value".to_owned()),
                TokenKind::Eq,
                TokenKind::Identifier("open".to_owned()),
                TokenKind::Plus,
                TokenKind::Identifier("high".to_owned()),
                TokenKind::Plus,
                TokenKind::Identifier("low".to_owned()),
                TokenKind::Plus,
                TokenKind::Identifier("close".to_owned()),
                TokenKind::Newline,
                TokenKind::If,
                TokenKind::True,
                TokenKind::Newline,
                TokenKind::Indent,
                TokenKind::Identifier("local".to_owned()),
                TokenKind::Eq,
                TokenKind::Identifier("open".to_owned()),
                TokenKind::Plus,
                TokenKind::Identifier("close".to_owned()),
                TokenKind::Newline,
                TokenKind::Identifier("plot".to_owned()),
                TokenKind::LParen,
                TokenKind::Identifier("local".to_owned()),
                TokenKind::RParen,
                TokenKind::Newline,
                TokenKind::Dedent,
                TokenKind::Eof,
            ]
        );
    }

    #[test]
    fn preserves_layout_for_multiple_of_four_outside_parentheses() {
        assert_eq!(
            kinds("value = open +\n    high\n"),
            vec![
                TokenKind::Identifier("value".to_owned()),
                TokenKind::Eq,
                TokenKind::Identifier("open".to_owned()),
                TokenKind::Plus,
                TokenKind::Newline,
                TokenKind::Indent,
                TokenKind::Identifier("high".to_owned()),
                TokenKind::Newline,
                TokenKind::Dedent,
                TokenKind::Eof,
            ]
        );
    }
}
