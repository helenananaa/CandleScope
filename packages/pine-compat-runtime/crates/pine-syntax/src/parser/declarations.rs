use crate::{DeclaredType, Span, TokenKind};

use super::Parser;

impl Parser {
    pub(super) fn try_parse_typed_decl_name(&mut self) -> Option<(DeclaredType, String, Span)> {
        if let Some(parsed) = self.try_parse_array_typed_decl_name() {
            return Some(parsed);
        }
        if let Some(parsed) = self.try_parse_matrix_typed_decl_name() {
            return Some(parsed);
        }
        if let Some(parsed) = self.try_parse_map_typed_decl_name() {
            return Some(parsed);
        }
        if let Some(parsed) = self.try_parse_array_type_alias_decl_name() {
            return Some(parsed);
        }

        if let TokenKind::Identifier(type_name) = self.current().kind.clone()
            && self.nth_at(2, TokenKind::Eq)
        {
            let TokenKind::Identifier(name) = self.tokens.get(self.pos + 1)?.kind.clone() else {
                return None;
            };
            let start = self.current().span;
            self.bump();
            self.bump();
            return Some((DeclaredType::Named(type_name), name, start));
        }

        if !self.nth_at(1, TokenKind::Dot) || !self.nth_at(4, TokenKind::Eq) {
            return None;
        }

        let TokenKind::Identifier(namespace) = self.current().kind.clone() else {
            return None;
        };
        let TokenKind::Identifier(type_name) = self.tokens.get(self.pos + 2)?.kind.clone() else {
            return None;
        };
        let TokenKind::Identifier(name) = self.tokens.get(self.pos + 3)?.kind.clone() else {
            return None;
        };

        let start = self.current().span;
        self.bump();
        self.bump();
        self.bump();
        self.bump();
        Some((
            DeclaredType::Named(format!("{namespace}.{type_name}")),
            name,
            start,
        ))
    }

    fn try_parse_array_typed_decl_name(&mut self) -> Option<(DeclaredType, String, Span)> {
        let TokenKind::Identifier(container) = self.current().kind.clone() else {
            return None;
        };
        if container != "array" || !self.nth_at(1, TokenKind::Lt) {
            return None;
        }

        let start_pos = self.pos;
        let (element_type, name_offset, eq_offset) = if self.nth_at(3, TokenKind::Gt)
            && self.nth_at(5, TokenKind::Eq)
        {
            let TokenKind::Identifier(element_type) = self.tokens.get(self.pos + 2)?.kind.clone()
            else {
                return None;
            };
            (element_type, 4, 5)
        } else if self.nth_at(3, TokenKind::Dot)
            && self.nth_at(5, TokenKind::Gt)
            && self.nth_at(7, TokenKind::Eq)
        {
            let TokenKind::Identifier(namespace) = self.tokens.get(self.pos + 2)?.kind.clone()
            else {
                return None;
            };
            let TokenKind::Identifier(type_name) = self.tokens.get(self.pos + 4)?.kind.clone()
            else {
                return None;
            };
            (format!("{namespace}.{type_name}"), 6, 7)
        } else {
            return None;
        };

        let TokenKind::Identifier(name) = self.tokens.get(self.pos + name_offset)?.kind.clone()
        else {
            return None;
        };

        let start = self.current().span;
        while self.pos < start_pos + eq_offset {
            self.bump();
        }
        Some((DeclaredType::Array { element_type }, name, start))
    }

    fn try_parse_matrix_typed_decl_name(&mut self) -> Option<(DeclaredType, String, Span)> {
        let TokenKind::Identifier(container) = self.current().kind.clone() else {
            return None;
        };
        if container != "matrix" || !self.nth_at(1, TokenKind::Lt) {
            return None;
        }

        let start_pos = self.pos;
        let (element_type, name_offset, eq_offset) = if self.nth_at(3, TokenKind::Gt)
            && self.nth_at(5, TokenKind::Eq)
        {
            let TokenKind::Identifier(element_type) = self.tokens.get(self.pos + 2)?.kind.clone()
            else {
                return None;
            };
            (element_type, 4, 5)
        } else {
            return None;
        };

        let TokenKind::Identifier(name) = self.tokens.get(self.pos + name_offset)?.kind.clone()
        else {
            return None;
        };

        let start = self.current().span;
        while self.pos < start_pos + eq_offset {
            self.bump();
        }
        Some((DeclaredType::Matrix { element_type }, name, start))
    }

    fn try_parse_map_typed_decl_name(&mut self) -> Option<(DeclaredType, String, Span)> {
        let TokenKind::Identifier(container) = self.current().kind.clone() else {
            return None;
        };
        if container != "map" || !self.nth_at(1, TokenKind::Lt) {
            return None;
        }

        let start_pos = self.pos;
        let (key_type, value_type, name_offset, eq_offset) = if self.nth_at(3, TokenKind::Comma)
            && self.nth_at(5, TokenKind::Gt)
            && self.nth_at(7, TokenKind::Eq)
        {
            let TokenKind::Identifier(key_type) = self.tokens.get(self.pos + 2)?.kind.clone()
            else {
                return None;
            };
            let TokenKind::Identifier(value_type) = self.tokens.get(self.pos + 4)?.kind.clone()
            else {
                return None;
            };
            (key_type, value_type, 6, 7)
        } else {
            return None;
        };

        let TokenKind::Identifier(name) = self.tokens.get(self.pos + name_offset)?.kind.clone()
        else {
            return None;
        };

        let start = self.current().span;
        while self.pos < start_pos + eq_offset {
            self.bump();
        }
        Some((
            DeclaredType::Map {
                key_type,
                value_type,
            },
            name,
            start,
        ))
    }

    fn try_parse_array_type_alias_decl_name(&mut self) -> Option<(DeclaredType, String, Span)> {
        let TokenKind::Identifier(first_type_name) = self.current().kind.clone() else {
            return None;
        };

        let (element_type, name_offset, eq_offset) = if self.nth_at(1, TokenKind::LBracket)
            && self.nth_at(2, TokenKind::RBracket)
            && self.nth_at(4, TokenKind::Eq)
        {
            (first_type_name, 3, 4)
        } else if self.nth_at(1, TokenKind::Dot)
            && self.nth_at(3, TokenKind::LBracket)
            && self.nth_at(4, TokenKind::RBracket)
            && self.nth_at(6, TokenKind::Eq)
        {
            let TokenKind::Identifier(type_name) = self.tokens.get(self.pos + 2)?.kind.clone()
            else {
                return None;
            };
            (format!("{first_type_name}.{type_name}"), 5, 6)
        } else {
            return None;
        };

        let TokenKind::Identifier(name) = self.tokens.get(self.pos + name_offset)?.kind.clone()
        else {
            return None;
        };

        let start = self.current().span;
        let start_pos = self.pos;
        while self.pos < start_pos + eq_offset {
            self.bump();
        }
        Some((DeclaredType::Array { element_type }, name, start))
    }
}
