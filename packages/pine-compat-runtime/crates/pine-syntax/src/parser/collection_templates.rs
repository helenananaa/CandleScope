use crate::{Expr, ExprKind, TokenKind};

use super::Parser;

impl Parser {
    pub(super) fn parse_collection_new_template_callee(&mut self, callee: &Expr) -> Option<Expr> {
        let (builtin_name, close_offset) = match &callee.kind {
            ExprKind::QualifiedName(parts) if parts.as_slice() == ["array", "new"] => {
                let (builtin_name, close_offset) = self.parse_supported_array_new_template()?;
                (builtin_name.to_owned(), close_offset)
            }
            ExprKind::QualifiedName(parts) if parts.as_slice() == ["matrix", "new"] => {
                self.parse_supported_matrix_new_template()?
            }
            ExprKind::QualifiedName(parts) if parts.as_slice() == ["map", "new"] => {
                self.parse_supported_map_new_template()?
            }
            _ => return None,
        };

        for _ in 0..close_offset {
            self.bump();
        }
        let end = self.current().span;
        self.bump();

        Some(Expr {
            span: callee.span.merge(end),
            kind: ExprKind::Identifier(builtin_name),
        })
    }

    fn parse_supported_array_new_template(&self) -> Option<(String, usize)> {
        if !self.at(TokenKind::Lt) {
            return None;
        }

        if self.nth_at(2, TokenKind::Gt) && self.nth_at(3, TokenKind::LParen) {
            return match &self.tokens.get(self.pos + 1)?.kind {
                TokenKind::Identifier(type_name) if type_name == "float" => {
                    Some(("array.new_float".to_owned(), 2))
                }
                TokenKind::Identifier(type_name) if type_name == "int" => {
                    Some(("array.new_int".to_owned(), 2))
                }
                TokenKind::Identifier(type_name) if type_name == "bool" => {
                    Some(("array.new_bool".to_owned(), 2))
                }
                TokenKind::Identifier(type_name) if type_name == "string" => {
                    Some(("array.new_string".to_owned(), 2))
                }
                TokenKind::Identifier(type_name) if type_name == "color" => {
                    Some(("array.new_color".to_owned(), 2))
                }
                TokenKind::Identifier(type_name) if type_name == "label" => {
                    Some(("array.new_label".to_owned(), 2))
                }
                TokenKind::Identifier(type_name) if type_name == "line" => {
                    Some(("array.new_line".to_owned(), 2))
                }
                TokenKind::Identifier(type_name) if type_name == "linefill" => {
                    Some(("array.new_linefill".to_owned(), 2))
                }
                TokenKind::Identifier(type_name) if type_name == "polyline" => {
                    Some(("array.new_polyline".to_owned(), 2))
                }
                TokenKind::Identifier(type_name) if type_name == "box" => {
                    Some(("array.new_box".to_owned(), 2))
                }
                TokenKind::Identifier(type_name) if type_name == "table" => {
                    Some(("array.new_table".to_owned(), 2))
                }
                TokenKind::Identifier(type_name) => Some((format!("array.new<{type_name}>"), 2)),
                _ => None,
            };
        }

        if self.nth_identifier_is(1, "chart")
            && self.nth_at(2, TokenKind::Dot)
            && self.nth_identifier_is(3, "point")
            && self.nth_at(4, TokenKind::Gt)
            && self.nth_at(5, TokenKind::LParen)
        {
            return Some(("array.new<chart.point>".to_owned(), 4));
        }

        let (type_name, type_width) = self.template_type_name_at(1)?;
        let close_offset = 1 + type_width;
        if self.nth_at(close_offset, TokenKind::Gt)
            && self.nth_at(close_offset + 1, TokenKind::LParen)
        {
            return Some((format!("array.new<{type_name}>"), close_offset));
        }

        None
    }

    fn parse_supported_matrix_new_template(&self) -> Option<(String, usize)> {
        if !self.at(TokenKind::Lt) {
            return None;
        }

        if self.nth_at(2, TokenKind::Gt) && self.nth_at(3, TokenKind::LParen) {
            let TokenKind::Identifier(type_name) = &self.tokens.get(self.pos + 1)?.kind else {
                return None;
            };
            return Some((format!("matrix.new<{type_name}>"), 2));
        }

        if self.nth_identifier_is(1, "chart")
            && self.nth_at(2, TokenKind::Dot)
            && self.nth_identifier_is(3, "point")
            && self.nth_at(4, TokenKind::Gt)
            && self.nth_at(5, TokenKind::LParen)
        {
            return Some(("matrix.new<chart.point>".to_owned(), 4));
        }

        None
    }

    fn parse_supported_map_new_template(&self) -> Option<(String, usize)> {
        if !self.at(TokenKind::Lt) {
            return None;
        }

        let (key_type, key_width) = self.template_type_name_at(1)?;
        let comma_offset = 1 + key_width;
        if !self.nth_at(comma_offset, TokenKind::Comma) {
            return None;
        }
        let value_offset = comma_offset + 1;
        let (value_type, value_width) = self.template_type_name_at(value_offset)?;
        let close_offset = value_offset + value_width;
        if self.nth_at(close_offset, TokenKind::Gt)
            && self.nth_at(close_offset + 1, TokenKind::LParen)
        {
            return Some((format!("map.new<{key_type},{value_type}>"), close_offset));
        }

        None
    }

    fn template_type_name_at(&self, offset: usize) -> Option<(String, usize)> {
        let TokenKind::Identifier(first) = &self.tokens.get(self.pos + offset)?.kind else {
            return None;
        };

        if self.nth_at(offset + 1, TokenKind::Dot) {
            let TokenKind::Identifier(second) = &self.tokens.get(self.pos + offset + 2)?.kind
            else {
                return None;
            };
            return Some((format!("{first}.{second}"), 3));
        }

        Some((first.clone(), 1))
    }
}
