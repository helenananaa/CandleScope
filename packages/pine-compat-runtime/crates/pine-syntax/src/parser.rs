use crate::{
    BinaryOp, CallArg, Diagnostic, Expr, ExprKind, Lexed, Literal, Program, SourceFile, Span, Stmt,
    SwitchArm, SwitchArmResult, Token, TokenKind, UnaryOp, VersionDecl, lex,
};

mod collection_templates;
mod declarations;
#[path = "parser_phase_j.rs"]
mod phase_j;
mod statements;

const MAX_EXPR_DEPTH: u32 = 256;

#[derive(Debug, Clone, PartialEq)]
pub struct Parse {
    pub program: Program,
    pub diagnostics: Vec<Diagnostic>,
}

pub fn parse_source(source: &SourceFile) -> Parse {
    let lexed = lex(source);
    Parser::new(lexed).parse()
}

struct Parser {
    tokens: Vec<Token>,
    pos: usize,
    diagnostics: Vec<Diagnostic>,
    expr_depth: u32,
}

struct ForParts {
    start: Span,
    counter: String,
    from: Expr,
    to: Expr,
    step: Option<Expr>,
    body: Vec<Stmt>,
    span: Span,
}

struct ForInParts {
    start: Span,
    index: Option<String>,
    value: String,
    iterable: Expr,
    body: Vec<Stmt>,
    span: Span,
}

impl Parser {
    fn new(lexed: Lexed) -> Self {
        Self {
            tokens: lexed.tokens,
            pos: 0,
            diagnostics: lexed.diagnostics,
            expr_depth: 0,
        }
    }

    fn parse(mut self) -> Parse {
        let version = self.parse_optional_version();
        let mut saw_version_directive = version.is_some();
        let mut statements = Vec::new();

        while !self.at(TokenKind::Eof) {
            self.skip_newlines();
            if self.at(TokenKind::Eof) {
                break;
            }
            if matches!(self.current().kind, TokenKind::VersionDirective(_)) {
                let (code, message) = if saw_version_directive {
                    (
                        "E_LANGUAGE_VERSION_DUPLICATE",
                        "source contains more than one version directive",
                    )
                } else {
                    (
                        "E_LANGUAGE_VERSION_PLACEMENT",
                        "version directive must appear before source statements",
                    )
                };
                self.diagnostics
                    .push(Diagnostic::error(code, message, self.current().span));
                saw_version_directive = true;
                self.bump();
                continue;
            }

            match self.parse_stmt() {
                Some(statement) => statements.push(statement),
                None => self.recover_stmt(),
            }
            self.skip_newlines();
        }

        Parse {
            program: Program {
                version,
                statements,
            },
            diagnostics: self.diagnostics,
        }
    }

    fn parse_optional_version(&mut self) -> Option<VersionDecl> {
        self.skip_newlines();
        match self.current().kind {
            TokenKind::VersionDirective(version) => {
                let span = self.current().span;
                self.bump();
                Some(VersionDecl { version, span })
            }
            _ => None,
        }
    }

    fn parse_expr(&mut self, min_bp: u8) -> Option<Expr> {
        if self.expr_depth >= MAX_EXPR_DEPTH {
            self.error_here("E_PARSE_EXPR_DEPTH", "expression nesting is too deep");
            return None;
        }

        self.expr_depth += 1;
        let result = self.parse_expr_inner(min_bp);
        self.expr_depth -= 1;
        result
    }

    fn parse_expr_inner(&mut self, min_bp: u8) -> Option<Expr> {
        let mut left = self.parse_prefix()?;

        loop {
            if matches!(
                left.kind,
                ExprKind::If { .. }
                    | ExprKind::For { .. }
                    | ExprKind::ForIn { .. }
                    | ExprKind::While { .. }
                    | ExprKind::Switch { .. }
            ) {
                break;
            }
            if let Some(template_callee) = self.parse_collection_new_template_callee(&left) {
                left = self.finish_call(template_callee)?;
                continue;
            }
            if self.at(TokenKind::LParen) {
                left = self.finish_call(left)?;
                continue;
            }
            if self.at(TokenKind::Dot)
                && self.nth_is_identifier(1)
                && self.nth_at(2, TokenKind::LParen)
            {
                left = self.finish_call_result_method_call(left)?;
                continue;
            }
            if self.at(TokenKind::LBracket) {
                left = self.finish_history(left)?;
                continue;
            }
            if self.at(TokenKind::Question) {
                // The ternary `?:` operator has the lowest binding power and is
                // right-associative, so it only binds at the top of an
                // expression (when `min_bp == 0`).
                const TERNARY_BINDING_POWER: u8 = 0;
                if TERNARY_BINDING_POWER < min_bp {
                    break;
                }
                self.bump();
                let then_expr = self.parse_expr(0)?;
                self.expect(TokenKind::Colon, "expected `:` in ternary expression")?;
                let else_expr = self.parse_expr(0)?;
                let span = left.span.merge(else_expr.span);
                left = Expr {
                    span,
                    kind: ExprKind::Ternary {
                        condition: Box::new(left),
                        then_expr: Box::new(then_expr),
                        else_expr: Box::new(else_expr),
                    },
                };
                continue;
            }

            let Some((op, left_bp, right_bp)) = self.current_binary_op() else {
                break;
            };
            if left_bp < min_bp {
                break;
            }

            self.bump();
            let right = self.parse_expr(right_bp)?;
            let span = left.span.merge(right.span);
            left = Expr {
                span,
                kind: ExprKind::Binary {
                    op,
                    left: Box::new(left),
                    right: Box::new(right),
                },
            };
        }

        Some(left)
    }

    fn parse_prefix(&mut self) -> Option<Expr> {
        let token = self.current().clone();
        match token.kind {
            TokenKind::Int(value) => {
                self.bump();
                Some(Expr {
                    span: token.span,
                    kind: ExprKind::Literal(Literal::Int(value)),
                })
            }
            TokenKind::Float(value) => {
                self.bump();
                Some(Expr {
                    span: token.span,
                    kind: ExprKind::Literal(Literal::Float(value)),
                })
            }
            TokenKind::String(value) => {
                self.bump();
                Some(Expr {
                    span: token.span,
                    kind: ExprKind::Literal(Literal::String(value)),
                })
            }
            TokenKind::ColorHex(value) => {
                self.bump();
                Some(Expr {
                    span: token.span,
                    kind: ExprKind::Literal(Literal::ColorHex(value)),
                })
            }
            TokenKind::True | TokenKind::False => {
                self.bump();
                Some(Expr {
                    span: token.span,
                    kind: ExprKind::Literal(Literal::Bool(matches!(token.kind, TokenKind::True))),
                })
            }
            TokenKind::Identifier(name) => {
                self.bump();
                self.parse_identifier_tail(name, token.span)
            }
            TokenKind::While => self.parse_while_expr(),
            TokenKind::Plus | TokenKind::Minus | TokenKind::Not => {
                self.bump();
                let op = match token.kind {
                    TokenKind::Plus => UnaryOp::Plus,
                    TokenKind::Minus => UnaryOp::Minus,
                    TokenKind::Not => UnaryOp::Not,
                    _ => unreachable!(),
                };
                let expr = self.parse_expr(12)?;
                Some(Expr {
                    span: token.span.merge(expr.span),
                    kind: ExprKind::Unary {
                        op,
                        expr: Box::new(expr),
                    },
                })
            }
            TokenKind::LParen => {
                self.bump();
                let expr = self.parse_expr(0)?;
                self.expect(TokenKind::RParen, "expected `)`")?;
                Some(expr)
            }
            TokenKind::For => self.parse_for_expr(),
            TokenKind::If => self.parse_if_expr(),
            TokenKind::Switch => self.parse_switch_expr(),
            TokenKind::LBracket => self.parse_tuple_expr(),
            _ => {
                self.error_here("E_PARSE_EXPR", "expected expression");
                None
            }
        }
    }

    fn parse_for_expr(&mut self) -> Option<Expr> {
        let start = self.expect(TokenKind::For, "expected `for`")?;
        if self.at(TokenKind::LBracket) {
            let (key, value) = self.parse_for_in_pair()?;
            let parts = self.parse_for_in_tail(start, Some(key), value)?;
            return Some(Expr {
                span: parts.start.merge(parts.span),
                kind: ExprKind::ForIn {
                    index: parts.index,
                    value: parts.value,
                    iterable: Box::new(parts.iterable),
                    body: parts.body,
                },
            });
        }
        let counter = self.parse_for_counter()?;
        if self.at(TokenKind::Comma) {
            self.bump();
            let value = self.parse_for_counter()?;
            let parts = self.parse_for_in_tail(start, Some(counter), value)?;
            return Some(Expr {
                span: parts.start.merge(parts.span),
                kind: ExprKind::ForIn {
                    index: parts.index,
                    value: parts.value,
                    iterable: Box::new(parts.iterable),
                    body: parts.body,
                },
            });
        }
        if self.nth_identifier_is(0, "in") {
            let parts = self.parse_for_in_tail(start, None, counter)?;
            return Some(Expr {
                span: parts.start.merge(parts.span),
                kind: ExprKind::ForIn {
                    index: parts.index,
                    value: parts.value,
                    iterable: Box::new(parts.iterable),
                    body: parts.body,
                },
            });
        }
        let parts = self.parse_for_range_tail(start, counter)?;

        Some(Expr {
            span: parts.start.merge(parts.span),
            kind: ExprKind::For {
                counter: parts.counter,
                from: Box::new(parts.from),
                to: Box::new(parts.to),
                step: parts.step.map(Box::new),
                body: parts.body,
            },
        })
    }

    fn parse_while_expr(&mut self) -> Option<Expr> {
        let start = self.expect(TokenKind::While, "expected `while`")?;
        let condition = self.parse_expr(0)?;
        self.expect(
            TokenKind::Newline,
            "expected newline after `while` condition",
        )?;
        let body = self.parse_indented_block()?;
        let span = body
            .last()
            .map_or(condition.span, |statement| statement.span);

        Some(Expr {
            span: start.merge(span),
            kind: ExprKind::While {
                condition: Box::new(condition),
                body,
            },
        })
    }

    fn parse_if_expr(&mut self) -> Option<Expr> {
        let start = self.expect(TokenKind::If, "expected `if`")?;
        let condition = self.parse_expr(0)?;
        self.expect(TokenKind::Newline, "expected newline after `if` condition")?;
        let then_branch = self.parse_indented_block()?;
        let mut span = then_branch
            .last()
            .map_or(condition.span, |statement| statement.span);

        if !self.at(TokenKind::Else) {
            self.diagnostics.push(Diagnostic::error(
                "E_PARSE_IF_EXPR",
                "if expressions require an else branch",
                start.merge(span),
            ));
            return None;
        }

        self.bump();
        if self.at(TokenKind::If) {
            self.diagnostics.push(Diagnostic::error(
                "E_PARSE_IF_EXPR",
                "else-if expression branches are not supported; use a nested if expression in the else branch",
                self.current().span,
            ));
            return None;
        }
        self.expect(TokenKind::Newline, "expected newline after `else`")?;
        let else_branch = self.parse_indented_block()?;
        span = else_branch.last().map_or(span, |statement| statement.span);

        Some(Expr {
            span: start.merge(span),
            kind: ExprKind::If {
                condition: Box::new(condition),
                then_branch,
                else_branch,
            },
        })
    }

    fn parse_switch_expr(&mut self) -> Option<Expr> {
        let start = self.expect(TokenKind::Switch, "expected `switch`")?;
        let selector = if self.at(TokenKind::Newline) {
            None
        } else {
            Some(Box::new(self.parse_expr(0)?))
        };
        self.expect(TokenKind::Newline, "expected newline after `switch`")?;
        self.expect(TokenKind::Indent, "expected indented switch arms")?;
        let mut arms = Vec::new();
        let mut end = selector.as_ref().map_or(start, |selector| selector.span);

        loop {
            self.skip_newlines();
            if self.at(TokenKind::Dedent) {
                self.bump();
                break;
            }
            if self.at(TokenKind::Eof) {
                self.error_here("E_PARSE_SWITCH", "expected dedent before end of switch");
                break;
            }

            let condition = if self.at(TokenKind::Arrow) {
                None
            } else {
                Some(self.parse_expr(0)?)
            };
            self.expect(TokenKind::Arrow, "expected `=>` in switch arm")?;
            let (result, result_is_block) = if self.at(TokenKind::Newline) {
                self.bump();
                let block = self.parse_indented_block()?;
                end = block.last().map_or(end, |statement| statement.span);
                (SwitchArmResult::Block(block), true)
            } else {
                let result = self.parse_expr(0)?;
                end = result.span;
                (SwitchArmResult::Expr(result), false)
            };
            arms.push(SwitchArm { condition, result });

            if result_is_block {
                continue;
            } else if self.at(TokenKind::Newline) {
                self.bump();
            } else if !self.at(TokenKind::Dedent) && !self.at(TokenKind::Eof) {
                self.error_here("E_PARSE_SWITCH", "expected newline after switch arm");
                return None;
            }
        }

        if arms.is_empty() {
            self.diagnostics.push(Diagnostic::error(
                "E_PARSE_SWITCH",
                "expected at least one switch arm",
                start,
            ));
            return None;
        }

        Some(Expr {
            span: start.merge(end),
            kind: ExprKind::Switch { selector, arms },
        })
    }

    fn parse_tuple_expr(&mut self) -> Option<Expr> {
        let start = self.expect(TokenKind::LBracket, "expected `[`")?;
        let mut items = Vec::new();

        if !self.at(TokenKind::RBracket) {
            loop {
                items.push(self.parse_expr(0)?);
                if self.at(TokenKind::Comma) {
                    self.bump();
                    continue;
                }
                break;
            }
        }

        let end = self.expect(TokenKind::RBracket, "expected `]` after tuple expression")?;
        Some(Expr {
            span: start.merge(end),
            kind: ExprKind::Tuple(items),
        })
    }

    fn parse_identifier_tail(&mut self, first: String, first_span: Span) -> Option<Expr> {
        let mut parts = vec![first];
        let mut span = first_span;

        while self.at(TokenKind::Dot) {
            self.bump();
            match self.current().kind.clone() {
                TokenKind::Identifier(part) => {
                    span = span.merge(self.current().span);
                    parts.push(part);
                    self.bump();
                }
                _ => {
                    self.error_here("E_PARSE_NAME", "expected identifier after `.`");
                    return None;
                }
            }
        }

        Some(Expr {
            span,
            kind: if parts.len() == 1 {
                ExprKind::Identifier(parts.pop().expect("parts has one item"))
            } else {
                ExprKind::QualifiedName(parts)
            },
        })
    }

    fn finish_call(&mut self, callee: Expr) -> Option<Expr> {
        let start = callee.span;
        self.expect(TokenKind::LParen, "expected `(`")?;
        let mut args = Vec::new();

        if !self.at(TokenKind::RParen) {
            loop {
                let arg_start = self.current().span;
                let name = if let TokenKind::Identifier(name) = self.current().kind.clone() {
                    if self.nth_at(1, TokenKind::Eq) {
                        self.bump();
                        self.bump();
                        Some(name)
                    } else {
                        None
                    }
                } else {
                    None
                };
                let value = self.parse_expr(0)?;
                args.push(CallArg {
                    span: arg_start.merge(value.span),
                    name,
                    value,
                });

                if self.at(TokenKind::Comma) {
                    self.bump();
                    continue;
                }
                break;
            }
        }

        let end = self.expect(TokenKind::RParen, "expected `)` after arguments")?;
        Some(Expr {
            span: start.merge(end),
            kind: ExprKind::Call {
                callee: Box::new(callee),
                args,
            },
        })
    }

    fn finish_call_result_method_call(&mut self, receiver: Expr) -> Option<Expr> {
        let Some(prefix) = call_result_receiver_prefix(&receiver) else {
            self.error_here(
                "E_PARSE_EXPR",
                "method calls on call-result receivers require an unqualified call, qualified user-defined result, or supported built-in collection producer receiver",
            );
            return None;
        };
        let start = receiver.span;
        let receiver_span = receiver.span;
        self.expect(TokenKind::Dot, "expected `.` before method name")?;
        let method_span = self.current().span;
        let TokenKind::Identifier(method_name) = self.current().kind.clone() else {
            self.error_here("E_PARSE_NAME", "expected method name after `.`");
            return None;
        };
        self.bump();
        self.expect(TokenKind::LParen, "expected `(` after method name")?;

        let mut args = vec![CallArg {
            name: None,
            value: receiver,
            span: receiver_span,
        }];

        if !self.at(TokenKind::RParen) {
            loop {
                let arg_start = self.current().span;
                let name = if let TokenKind::Identifier(name) = self.current().kind.clone() {
                    if self.nth_at(1, TokenKind::Eq) {
                        self.bump();
                        self.bump();
                        Some(name)
                    } else {
                        None
                    }
                } else {
                    None
                };
                let value = self.parse_expr(0)?;
                args.push(CallArg {
                    span: arg_start.merge(value.span),
                    name,
                    value,
                });

                if self.at(TokenKind::Comma) {
                    self.bump();
                    continue;
                }
                break;
            }
        }

        let end = self.expect(TokenKind::RParen, "expected `)` after arguments")?;
        Some(Expr {
            span: start.merge(end),
            kind: ExprKind::Call {
                callee: Box::new(Expr {
                    span: method_span,
                    kind: ExprKind::QualifiedName(vec![prefix, method_name]),
                }),
                args,
            },
        })
    }

    fn finish_history(&mut self, expr: Expr) -> Option<Expr> {
        self.expect(TokenKind::LBracket, "expected `[`")?;
        let offset = self.parse_expr(0)?;
        let end = self.expect(TokenKind::RBracket, "expected `]` after history offset")?;
        Some(Expr {
            span: expr.span.merge(end),
            kind: ExprKind::History {
                expr: Box::new(expr),
                offset: Box::new(offset),
            },
        })
    }

    fn current_binary_op(&self) -> Option<(BinaryOp, u8, u8)> {
        match self.current().kind {
            TokenKind::Or => Some((BinaryOp::Or, 2, 3)),
            TokenKind::And => Some((BinaryOp::And, 4, 5)),
            TokenKind::EqEq => Some((BinaryOp::Eq, 6, 7)),
            TokenKind::BangEq => Some((BinaryOp::NotEq, 6, 7)),
            TokenKind::Gt => Some((BinaryOp::Gt, 8, 9)),
            TokenKind::Gte => Some((BinaryOp::Gte, 8, 9)),
            TokenKind::Lt => Some((BinaryOp::Lt, 8, 9)),
            TokenKind::Lte => Some((BinaryOp::Lte, 8, 9)),
            TokenKind::Plus => Some((BinaryOp::Add, 10, 11)),
            TokenKind::Minus => Some((BinaryOp::Sub, 10, 11)),
            TokenKind::Star => Some((BinaryOp::Mul, 12, 13)),
            TokenKind::Slash => Some((BinaryOp::Div, 12, 13)),
            TokenKind::Percent => Some((BinaryOp::Mod, 12, 13)),
            _ => None,
        }
    }

    fn nth_is_identifier(&self, n: usize) -> bool {
        matches!(
            self.tokens.get(self.pos + n).map(|token| &token.kind),
            Some(TokenKind::Identifier(_))
        )
    }

    fn skip_newlines(&mut self) {
        while self.at(TokenKind::Newline) {
            self.bump();
        }
    }

    fn recover_stmt(&mut self) {
        while !self.at(TokenKind::Newline) && !self.at(TokenKind::Eof) {
            self.bump();
        }
    }

    fn expect(&mut self, expected: TokenKind, message: &str) -> Option<Span> {
        if self.at(expected) {
            let span = self.current().span;
            self.bump();
            Some(span)
        } else {
            self.error_here("E_PARSE_EXPECTED", message);
            None
        }
    }

    fn error_here(&mut self, code: &str, message: &str) {
        self.diagnostics
            .push(Diagnostic::error(code, message, self.current().span));
    }

    fn at(&self, expected: TokenKind) -> bool {
        std::mem::discriminant(&self.current().kind) == std::mem::discriminant(&expected)
    }

    fn nth_at(&self, offset: usize, expected: TokenKind) -> bool {
        self.tokens.get(self.pos + offset).is_some_and(|token| {
            std::mem::discriminant(&token.kind) == std::mem::discriminant(&expected)
        })
    }

    fn nested_field_reassign_colon_eq_offset(&self) -> Option<usize> {
        let mut offset = 1;
        let mut field_count = 0;
        while self.nth_at(offset, TokenKind::Dot)
            && self
                .tokens
                .get(self.pos + offset + 1)
                .is_some_and(|token| matches!(token.kind, TokenKind::Identifier(_)))
        {
            field_count += 1;
            offset += 2;
        }
        (field_count >= 2 && self.nth_at(offset, TokenKind::ColonEq)).then_some(offset)
    }

    fn get_call_field_reassign_colon_eq_offset(&self) -> Option<usize> {
        if !self.nth_at(1, TokenKind::Dot)
            || !self.tokens.get(self.pos + 2).is_some_and(
                |token| matches!(&token.kind, TokenKind::Identifier(name) if name == "get"),
            )
            || !self.nth_at(3, TokenKind::LParen)
        {
            return None;
        }

        let mut offset = 3;
        let mut depth = 0usize;
        while let Some(token) = self.tokens.get(self.pos + offset) {
            match token.kind {
                TokenKind::LParen => depth += 1,
                TokenKind::RParen => {
                    depth = depth.saturating_sub(1);
                    if depth == 0 {
                        return (self.nth_at(offset + 1, TokenKind::Dot)
                            && self.tokens.get(self.pos + offset + 2).is_some_and(|token| {
                                matches!(token.kind, TokenKind::Identifier(_))
                            })
                            && self.nth_at(offset + 3, TokenKind::ColonEq))
                        .then_some(offset + 3);
                    }
                }
                TokenKind::Eof => break,
                _ => {}
            }
            offset += 1;
        }
        None
    }

    fn nth_identifier_is(&self, offset: usize, expected: &str) -> bool {
        self.tokens.get(self.pos + offset).is_some_and(
            |token| matches!(&token.kind, TokenKind::Identifier(name) if name == expected),
        )
    }

    fn current(&self) -> &Token {
        &self.tokens[self.pos]
    }

    fn previous(&self) -> &Token {
        &self.tokens[self.pos.saturating_sub(1)]
    }

    fn bump(&mut self) {
        if self.pos + 1 < self.tokens.len() {
            self.pos += 1;
        }
    }
}

fn call_result_receiver_prefix(receiver: &Expr) -> Option<String> {
    let ExprKind::Call { callee, .. } = &receiver.kind else {
        return None;
    };
    match &callee.kind {
        ExprKind::Identifier(name) if is_plain_identifier(name) => {
            Some(UNQUALIFIED_CALL_RESULT_PREFIX.to_owned())
        }
        ExprKind::Identifier(name) if is_builtin_array_result_callee(name) => {
            Some(BUILTIN_ARRAY_CALL_RESULT_PREFIX.to_owned())
        }
        ExprKind::Identifier(name) if is_builtin_matrix_result_callee(name) => {
            Some(BUILTIN_MATRIX_CALL_RESULT_PREFIX.to_owned())
        }
        ExprKind::Identifier(name) if is_builtin_map_result_callee(name) => {
            Some(BUILTIN_MAP_CALL_RESULT_PREFIX.to_owned())
        }
        ExprKind::QualifiedName(parts) => match parts.as_slice() {
            [prefix, method]
                if prefix == BUILTIN_MATRIX_CALL_RESULT_PREFIX
                    && matches!(
                        method.as_str(),
                        "row"
                            | "col"
                            | "eigenvalues"
                            | "slice"
                            | "concat"
                            | "abs"
                            | "standardize"
                            | "sort_indices"
                    ) =>
            {
                Some(BUILTIN_ARRAY_CALL_RESULT_PREFIX.to_owned())
            }
            [prefix, method]
                if prefix == BUILTIN_MATRIX_CALL_RESULT_PREFIX
                    && matches!(
                        method.as_str(),
                        "copy"
                            | "diff"
                            | "eigenvectors"
                            | "inv"
                            | "kron"
                            | "mult"
                            | "pinv"
                            | "pow"
                            | "submatrix"
                            | "transpose"
                    ) =>
            {
                Some(BUILTIN_MATRIX_CALL_RESULT_PREFIX.to_owned())
            }
            [prefix, _method] if prefix == BUILTIN_MATRIX_CALL_RESULT_PREFIX => None,
            [prefix, method]
                if prefix == BUILTIN_MAP_CALL_RESULT_PREFIX
                    && matches!(method.as_str(), "keys" | "values") =>
            {
                Some(BUILTIN_ARRAY_CALL_RESULT_PREFIX.to_owned())
            }
            [prefix, method] if prefix == BUILTIN_MAP_CALL_RESULT_PREFIX && method == "copy" => {
                Some(BUILTIN_MAP_CALL_RESULT_PREFIX.to_owned())
            }
            [prefix, _method] if prefix == BUILTIN_MAP_CALL_RESULT_PREFIX => None,
            [prefix, method]
                if prefix == BUILTIN_ARRAY_CALL_RESULT_PREFIX
                    && matches!(
                        method.as_str(),
                        "copy" | "slice" | "concat" | "abs" | "standardize" | "sort_indices"
                    ) =>
            {
                Some(BUILTIN_ARRAY_CALL_RESULT_PREFIX.to_owned())
            }
            [prefix, _method] if prefix == BUILTIN_ARRAY_CALL_RESULT_PREFIX => None,
            [namespace, member] if is_builtin_matrix_result_qualified_callee(namespace, member) => {
                Some(BUILTIN_MATRIX_CALL_RESULT_PREFIX.to_owned())
            }
            [namespace, member] if is_builtin_map_result_qualified_callee(namespace, member) => {
                Some(BUILTIN_MAP_CALL_RESULT_PREFIX.to_owned())
            }
            [namespace, member] if is_builtin_array_result_qualified_callee(namespace, member) => {
                Some(BUILTIN_ARRAY_CALL_RESULT_PREFIX.to_owned())
            }
            [alias, _method] if !is_builtin_namespace(alias) => Some(alias.clone()),
            [alias, _type_name, constructor]
                if constructor == "new" && !is_builtin_namespace(alias) =>
            {
                Some(alias.clone())
            }
            _ => None,
        },
        _ => None,
    }
}

const UNQUALIFIED_CALL_RESULT_PREFIX: &str = "$call_result";
const BUILTIN_ARRAY_CALL_RESULT_PREFIX: &str = "$builtin_array_result";
const BUILTIN_MATRIX_CALL_RESULT_PREFIX: &str = "$builtin_matrix_result";
const BUILTIN_MAP_CALL_RESULT_PREFIX: &str = "$builtin_map_result";

fn is_plain_identifier(name: &str) -> bool {
    let mut chars = name.chars();
    chars
        .next()
        .is_some_and(|ch| ch == '_' || ch.is_ascii_alphabetic())
        && chars.all(|ch| ch == '_' || ch.is_ascii_alphanumeric())
}

fn is_builtin_array_result_callee(name: &str) -> bool {
    name.strip_prefix("array.").is_some_and(|member| {
        is_builtin_array_result_member(member)
            || (member.starts_with("new<") && member.ends_with('>'))
    })
}

fn is_builtin_array_result_qualified_callee(namespace: &str, member: &str) -> bool {
    (namespace == "array" && is_builtin_array_result_member(member))
        || matches!(
            (namespace, member),
            ("str", "split")
                | ("ta", "pivot_point_levels")
                | ("matrix", "eigenvalues" | "row" | "col")
                | ("map", "keys" | "values")
        )
}

fn is_builtin_matrix_result_qualified_callee(namespace: &str, member: &str) -> bool {
    namespace == "matrix"
        && matches!(
            member,
            "copy"
                | "diff"
                | "eigenvectors"
                | "inv"
                | "kron"
                | "mult"
                | "pinv"
                | "pow"
                | "submatrix"
                | "transpose"
        )
}

fn is_builtin_map_result_qualified_callee(namespace: &str, member: &str) -> bool {
    namespace == "map" && member == "copy"
}

fn is_builtin_matrix_result_callee(name: &str) -> bool {
    matches!(
        name,
        "matrix.new<float>"
            | "matrix.new<int>"
            | "matrix.new<bool>"
            | "matrix.new<string>"
            | "matrix.new<color>"
    )
}

fn is_builtin_map_result_callee(name: &str) -> bool {
    let Some(inner) = name
        .strip_prefix("map.new<")
        .and_then(|name| name.strip_suffix('>'))
    else {
        return false;
    };
    let Some((key_type, value_type)) = inner.split_once(',') else {
        return false;
    };
    is_builtin_map_scalar_template(key_type) && is_builtin_map_scalar_template(value_type)
}

fn is_builtin_map_scalar_template(name: &str) -> bool {
    matches!(name, "int" | "float" | "bool" | "string" | "color")
}

fn is_builtin_array_result_member(member: &str) -> bool {
    matches!(
        member,
        "new_float"
            | "new_int"
            | "new_bool"
            | "new_string"
            | "new_color"
            | "new_line"
            | "new_linefill"
            | "new_polyline"
            | "new_label"
            | "new_box"
            | "new_table"
            | "from"
            | "copy"
            | "slice"
            | "concat"
            | "abs"
            | "standardize"
            | "sort_indices"
    )
}

fn is_builtin_namespace(name: &str) -> bool {
    matches!(
        name,
        "array"
            | "box"
            | "chart"
            | "color"
            | "hline"
            | "input"
            | "label"
            | "line"
            | "linefill"
            | "log"
            | "map"
            | "math"
            | "matrix"
            | "plot"
            | "polyline"
            | "request"
            | "str"
            | "strategy"
            | "syminfo"
            | "ta"
            | "table"
            | "ticker"
            | "timeframe"
    )
}
