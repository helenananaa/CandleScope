use crate::{
    Diagnostic, ExportDecl, ExportItem, FunctionBody, ImportAlias, ImportDecl, LibraryDecl,
    MethodDecl, MethodParam, Span, Stmt, StmtKind, TokenKind, UserTypeDecl, UserTypeField,
};

use super::Parser;

enum PhaseJStatement {
    Library,
    Export,
    UserType,
    Method,
}

impl Parser {
    pub(super) fn parse_import_decl(&mut self) -> Option<Stmt> {
        let start = self.expect(TokenKind::Import, "expected `import`")?;
        let key_start = self.current().span;
        let mut key_end = key_start;
        let mut key = String::new();
        let mut saw_key_part = false;

        while !self.at(TokenKind::Newline) && !self.at(TokenKind::Eof) {
            if self.current_identifier_is("as") {
                break;
            }
            match self.current().kind.clone() {
                TokenKind::Identifier(part) => {
                    key.push_str(&part);
                    key_end = self.current().span;
                    saw_key_part = true;
                    self.bump();
                }
                TokenKind::Int(part) => {
                    key.push_str(&part.to_string());
                    key_end = self.current().span;
                    saw_key_part = true;
                    self.bump();
                }
                TokenKind::Slash => {
                    key.push('/');
                    key_end = self.current().span;
                    self.bump();
                }
                _ => {
                    self.error_here("E_PARSE_IMPORT", "expected import key");
                    return None;
                }
            }
        }

        if !saw_key_part {
            self.diagnostics.push(Diagnostic::error(
                "E_PARSE_IMPORT",
                "expected import key",
                self.current().span,
            ));
            return None;
        }

        let alias = if self.current_identifier_is("as") {
            self.bump();
            let alias_span = self.current().span;
            match self.current().kind.clone() {
                TokenKind::Identifier(name) => {
                    self.bump();
                    Some(ImportAlias {
                        name,
                        span: alias_span,
                    })
                }
                _ => {
                    self.error_here("E_PARSE_IMPORT", "expected import alias after `as`");
                    return None;
                }
            }
        } else {
            None
        };

        let end = alias.as_ref().map_or(key_end, |alias| alias.span);
        Some(Stmt {
            span: start.merge(end),
            kind: StmtKind::Import(ImportDecl {
                key,
                key_span: key_start.merge(key_end),
                alias,
            }),
        })
    }

    pub(super) fn parse_phase_j_decl(&mut self) -> Option<Option<Stmt>> {
        match self.phase_j_statement() {
            Some(PhaseJStatement::Library) => self.parse_library_decl().map(Some),
            Some(PhaseJStatement::Export) => self.parse_export_decl().map(Some),
            Some(PhaseJStatement::UserType) => self.parse_user_type_decl().map(Some),
            Some(PhaseJStatement::Method) => self.parse_method_decl().map(Some),
            None => Some(None),
        }
    }

    fn parse_library_decl(&mut self) -> Option<Stmt> {
        let start = self.current().span;
        self.bump();
        self.expect(TokenKind::LParen, "expected `(` after `library`")?;
        let (name, name_span) = match self.current().kind.clone() {
            TokenKind::String(name) => {
                let span = self.current().span;
                self.bump();
                (Some(name), Some(span))
            }
            TokenKind::RParen => (None, None),
            _ => {
                self.error_here("E_PARSE_LIBRARY", "expected library name string");
                return None;
            }
        };
        let end = self.consume_call_tail()?;

        Some(Stmt {
            span: start.merge(end),
            kind: StmtKind::Library(LibraryDecl { name, name_span }),
        })
    }

    fn parse_export_decl(&mut self) -> Option<Stmt> {
        let start = self.current().span;
        self.bump();

        let item = if matches!(&self.current().kind, TokenKind::Identifier(name) if name == "type")
            && self.nth_identifier(1)
        {
            let user_type = self.parse_user_type_decl()?;
            match user_type.kind {
                StmtKind::UserType(decl) => ExportItem::UserType {
                    decl,
                    span: user_type.span,
                },
                _ => unreachable!(),
            }
        } else if self.looks_like_function_decl() {
            let function = self.parse_function_decl()?;
            match function.kind {
                StmtKind::Function { name, params, body } => ExportItem::Function {
                    name,
                    params,
                    body,
                    span: function.span,
                },
                _ => unreachable!(),
            }
        } else if let TokenKind::Identifier(name) = self.current().kind.clone() {
            let item_start = self.current().span;
            if self.nth_at(1, TokenKind::Eq) {
                self.bump();
                self.bump();
                let value = self.parse_expr(0)?;
                ExportItem::Const {
                    name,
                    span: item_start.merge(value.span),
                    value,
                }
            } else {
                let end = self.consume_to_line_end();
                ExportItem::Unknown {
                    span: item_start.merge(end),
                }
            }
        } else {
            self.error_here("E_PARSE_EXPORT", "expected exported declaration");
            return None;
        };

        let end = match &item {
            ExportItem::Function { span, .. }
            | ExportItem::Const { span, .. }
            | ExportItem::UserType { span, .. } => *span,
            ExportItem::Unknown { span } => *span,
        };
        Some(Stmt {
            span: start.merge(end),
            kind: StmtKind::Export(ExportDecl { item }),
        })
    }

    fn parse_user_type_decl(&mut self) -> Option<Stmt> {
        let start = self.current().span;
        self.bump();
        let (name, name_span) = self.expect_identifier("expected user-defined type name")?;
        let mut end = name_span;
        let fields = if self.at(TokenKind::Newline) && self.nth_at(1, TokenKind::Indent) {
            self.bump();
            self.expect(TokenKind::Indent, "expected type field block")?;
            let mut fields = Vec::new();
            loop {
                self.skip_newlines();
                if self.at(TokenKind::Dedent) {
                    end = self.current().span;
                    self.bump();
                    break;
                }
                if self.at(TokenKind::Eof) {
                    self.error_here("E_PARSE_TYPE", "expected dedent before end of type");
                    break;
                }
                let (type_name, type_span) = self.expect_field_type_name()?;
                let (field_name, field_span) = self.expect_identifier("expected field name")?;
                end = field_span;
                fields.push(UserTypeField {
                    type_name,
                    name: field_name,
                    span: type_span.merge(field_span),
                });
                self.consume_to_line_end();
                if self.at(TokenKind::Newline) {
                    self.bump();
                }
            }
            fields
        } else {
            Vec::new()
        };

        Some(Stmt {
            span: start.merge(end),
            kind: StmtKind::UserType(UserTypeDecl {
                name,
                name_span,
                fields,
            }),
        })
    }

    fn parse_method_decl(&mut self) -> Option<Stmt> {
        let start = self.current().span;
        self.bump();
        let (name, name_span) = self.expect_identifier("expected method name")?;
        self.expect(TokenKind::LParen, "expected `(` after method name")?;
        let params = self.parse_method_params()?;
        self.expect(TokenKind::RParen, "expected `)` after method parameters")?;
        self.expect(TokenKind::Arrow, "expected `=>` in method declaration")?;
        let (body, end) = if self.at(TokenKind::Newline) {
            self.bump();
            let block = self.parse_indented_block()?;
            let span = block.last().map_or(name_span, |statement| statement.span);
            (FunctionBody::Block(block), span)
        } else {
            let body = self.parse_expr(0)?;
            let span = body.span;
            (FunctionBody::Expr(body), span)
        };

        Some(Stmt {
            span: start.merge(end),
            kind: StmtKind::Method(MethodDecl {
                name,
                name_span,
                params,
                body,
            }),
        })
    }

    fn parse_method_params(&mut self) -> Option<Vec<MethodParam>> {
        let mut params = Vec::new();
        if self.at(TokenKind::RParen) {
            return Some(params);
        }

        loop {
            let Some(param) = self.parse_function_param() else {
                self.error_here("E_PARSE_METHOD", "expected method parameter");
                return None;
            };
            let Some(type_name) = param.type_name else {
                self.error_here("E_PARSE_METHOD", "method parameters must declare a type");
                return None;
            };
            params.push(MethodParam {
                type_name,
                name: param.name,
                span: param.span,
            });

            if self.at(TokenKind::Comma) {
                self.bump();
                continue;
            }
            break;
        }
        Some(params)
    }

    fn phase_j_statement(&self) -> Option<PhaseJStatement> {
        let TokenKind::Identifier(name) = &self.current().kind else {
            return None;
        };

        match name.as_str() {
            "library" if self.nth_at(1, TokenKind::LParen) => Some(PhaseJStatement::Library),
            "export" if self.nth_identifier(1) => Some(PhaseJStatement::Export),
            "type" if self.nth_identifier(1) => Some(PhaseJStatement::UserType),
            "method" if self.nth_identifier(1) => Some(PhaseJStatement::Method),
            _ => None,
        }
    }

    fn consume_call_tail(&mut self) -> Option<Span> {
        let mut depth = 1_u32;
        while !self.at(TokenKind::Eof) && !self.at(TokenKind::Newline) {
            let current_span = self.current().span;
            if self.at(TokenKind::LParen) {
                depth += 1;
                self.bump();
                continue;
            }
            if self.at(TokenKind::RParen) {
                depth = depth.saturating_sub(1);
                self.bump();
                if depth == 0 {
                    return Some(current_span);
                }
                continue;
            }
            self.bump();
        }
        self.error_here("E_PARSE_EXPECTED", "expected `)` after arguments");
        None
    }

    fn consume_to_line_end(&mut self) -> Span {
        let mut end = self.previous().span;
        while !self.at(TokenKind::Newline) && !self.at(TokenKind::Eof) {
            end = self.current().span;
            self.bump();
        }
        end
    }

    fn expect_identifier(&mut self, message: &str) -> Option<(String, Span)> {
        match self.current().kind.clone() {
            TokenKind::Identifier(name) => {
                let span = self.current().span;
                self.bump();
                Some((name, span))
            }
            _ => {
                self.error_here("E_PARSE_NAME", message);
                None
            }
        }
    }

    fn expect_field_type_name(&mut self) -> Option<(String, Span)> {
        let (first, first_span) = self.expect_identifier("expected field type")?;
        if self.at(TokenKind::Dot) {
            self.bump();
            let (second, second_span) =
                self.expect_identifier("expected field type name after `.`")?;
            return Some((format!("{first}.{second}"), first_span.merge(second_span)));
        }
        Some((first, first_span))
    }

    fn nth_identifier(&self, offset: usize) -> bool {
        self.tokens
            .get(self.pos + offset)
            .is_some_and(|token| matches!(token.kind, TokenKind::Identifier(_)))
    }

    fn current_identifier_is(&self, expected: &str) -> bool {
        matches!(&self.current().kind, TokenKind::Identifier(name) if name == expected)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{ExprKind, Literal, Parse, SourceFile, StmtKind, parse_source};

    fn parse(text: &str) -> Parse {
        parse_source(&SourceFile::new("test.pine", text))
    }

    #[test]
    fn parses_import_declaration() {
        let parsed = parse("import user/library/1 as lib\nindicator(\"Demo\")\n");

        assert!(parsed.diagnostics.is_empty(), "{:?}", parsed.diagnostics);
        assert_eq!(parsed.program.statements.len(), 2);
        let StmtKind::Import(import) = &parsed.program.statements[0].kind else {
            panic!("expected import statement");
        };
        assert_eq!(import.key, "user/library/1");
        let alias = import.alias.as_ref().expect("import alias");
        assert_eq!(alias.name, "lib");
    }

    #[test]
    fn parses_phase_j_declarations_as_structured_statements() {
        let parsed = parse(
            "library(\"Lib\")\nexport foo() => close\ntype Point\n    float x\nmethod scale(Point p) => p\n",
        );

        assert!(parsed.diagnostics.is_empty(), "{:?}", parsed.diagnostics);
        assert_eq!(parsed.program.statements.len(), 4);
        let StmtKind::Library(library) = &parsed.program.statements[0].kind else {
            panic!("expected library declaration");
        };
        assert_eq!(library.name.as_deref(), Some("Lib"));

        let StmtKind::Export(export) = &parsed.program.statements[1].kind else {
            panic!("expected export declaration");
        };
        let ExportItem::Function { name, params, .. } = &export.item else {
            panic!("expected exported function");
        };
        assert_eq!(name, "foo");
        assert!(params.is_empty());

        let StmtKind::UserType(user_type) = &parsed.program.statements[2].kind else {
            panic!("expected user-defined type");
        };
        assert_eq!(user_type.name, "Point");
        assert_eq!(user_type.fields.len(), 1);
        assert_eq!(user_type.fields[0].type_name, "float");
        assert_eq!(user_type.fields[0].name, "x");

        let StmtKind::Method(method) = &parsed.program.statements[3].kind else {
            panic!("expected method declaration");
        };
        assert_eq!(method.name, "scale");
        assert_eq!(method.params.len(), 1);
        assert_eq!(method.params[0].type_name, "Point");
        assert_eq!(method.params[0].name, "p");
    }

    #[test]
    fn parses_library_declaration_name_span() {
        let parsed = parse("library(\"Lib\")\n");

        assert!(parsed.diagnostics.is_empty(), "{:?}", parsed.diagnostics);
        let StmtKind::Library(library) = &parsed.program.statements[0].kind else {
            panic!("expected library declaration");
        };
        assert_eq!(library.name.as_deref(), Some("Lib"));
        assert!(library.name_span.is_some());
    }

    #[test]
    fn parses_exported_const_declaration() {
        let parsed = parse("export answer = 42\n");

        assert!(parsed.diagnostics.is_empty(), "{:?}", parsed.diagnostics);
        let StmtKind::Export(export) = &parsed.program.statements[0].kind else {
            panic!("expected export declaration");
        };
        let ExportItem::Const { name, value, .. } = &export.item else {
            panic!("expected exported const");
        };
        assert_eq!(name, "answer");
        assert!(matches!(value.kind, ExprKind::Literal(Literal::Int(42))));
    }

    #[test]
    fn parses_exported_user_type_declaration() {
        let parsed = parse("export type Point\n    float x\n");

        assert!(parsed.diagnostics.is_empty(), "{:?}", parsed.diagnostics);
        let StmtKind::Export(export) = &parsed.program.statements[0].kind else {
            panic!("expected export declaration");
        };
        let ExportItem::UserType { decl, .. } = &export.item else {
            panic!("expected exported user-defined type");
        };
        assert_eq!(decl.name, "Point");
        assert_eq!(decl.fields.len(), 1);
        assert_eq!(decl.fields[0].type_name, "float");
        assert_eq!(decl.fields[0].name, "x");
    }

    #[test]
    fn parses_user_type_object_and_chart_point_fields() {
        let parsed = parse(
            "type Handles\n    label id\n    line trend\n    box zone\n    chart.point anchor\n",
        );

        assert!(parsed.diagnostics.is_empty(), "{:?}", parsed.diagnostics);
        let StmtKind::UserType(user_type) = &parsed.program.statements[0].kind else {
            panic!("expected user-defined type");
        };
        assert_eq!(user_type.fields.len(), 4);
        assert_eq!(user_type.fields[0].type_name, "label");
        assert_eq!(user_type.fields[0].name, "id");
        assert_eq!(user_type.fields[1].type_name, "line");
        assert_eq!(user_type.fields[1].name, "trend");
        assert_eq!(user_type.fields[2].type_name, "box");
        assert_eq!(user_type.fields[2].name, "zone");
        assert_eq!(user_type.fields[3].type_name, "chart.point");
        assert_eq!(user_type.fields[3].name, "anchor");
    }

    #[test]
    fn parses_export_as_plain_identifier_when_not_followed_by_item_name() {
        let parsed = parse("export = 5\n");

        assert!(parsed.diagnostics.is_empty(), "{:?}", parsed.diagnostics);
        let StmtKind::Decl { name, value, .. } = &parsed.program.statements[0].kind else {
            panic!("expected ordinary declaration");
        };
        assert_eq!(name, "export");
        assert!(matches!(value.kind, ExprKind::Literal(Literal::Int(5))));
    }

    #[test]
    fn recovers_after_malformed_import_alias() {
        let parsed = parse("import user/library/1 as\nindicator(\"Demo\")\n");

        assert_eq!(parsed.program.statements.len(), 1);
        assert!(matches!(
            parsed.program.statements[0].kind,
            StmtKind::Expr(_)
        ));
        assert!(
            parsed
                .diagnostics
                .iter()
                .any(|diagnostic| diagnostic.code == "E_PARSE_IMPORT")
        );
    }

    #[test]
    fn parses_field_mutation_as_unsupported_boundary() {
        let parsed = parse("p.x := 1\n");

        let StmtKind::FieldReassign {
            receiver,
            field,
            value,
        } = &parsed.program.statements[0].kind
        else {
            panic!("expected field mutation");
        };
        assert_eq!(receiver, "p");
        assert_eq!(field, "x");
        assert!(matches!(value.kind, ExprKind::Literal(_)));
    }

    #[test]
    fn parses_nested_field_mutation_as_unsupported_boundary() {
        let parsed = parse("p.inner.x := 1\n");

        let StmtKind::Unsupported { feature } = &parsed.program.statements[0].kind else {
            panic!("expected unsupported nested field mutation");
        };
        assert_eq!(feature, "nested field mutation");
        assert!(
            !parsed
                .diagnostics
                .iter()
                .any(|diagnostic| diagnostic.code == "E_PARSE_EXPR"),
            "{:?}",
            parsed.diagnostics
        );
    }
}
