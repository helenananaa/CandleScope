use crate::{
    Analysis, AnalysisInput, CompileCache, CompileCacheStats, PineDialect, SourceGraphError,
};
use pine_ir::{HirStmtKind, PersistenceKind, VarSlotId};
use pine_syntax::SourceFile;

fn analyze(text: &str) -> Analysis {
    crate::analysis::analyze_source_with_implicit_dialect(
        &SourceFile::new("test.pine", text),
        PineDialect::V5,
    )
}

mod compatibility;
mod constant_call_semantics;
mod history_constant_calls;
mod legacy_dialect;
mod legacy_frontend;
mod lowering;
mod methods;
mod scopes;
mod type_arrays;
mod type_core;
mod type_inputs_outputs;
mod type_ta;
mod user_types;
