//! Syntax layer: source files, spans, diagnostics, lexer, AST, and parser.

mod ast;
mod diagnostic;
mod lexer;
mod parser;
#[cfg(test)]
mod parser_tests;
mod source;

pub use ast::{
    BinaryOp, CallArg, DeclMode, DeclaredType, ExportDecl, ExportItem, Expr, ExprKind,
    FunctionBody, FunctionParam, ImportAlias, ImportDecl, LibraryDecl, Literal, MethodDecl,
    MethodParam, Program, Stmt, StmtKind, SwitchArm, SwitchArmResult, UnaryOp, UserTypeDecl,
    UserTypeField, VersionDecl,
};
pub use diagnostic::{Diagnostic, Severity};
pub use lexer::{Lexed, Token, TokenKind, lex};
pub use parser::{Parse, parse_source};
pub use source::{LineCol, SourceFile, Span};
