use crate::{
    Analysis, AnalysisInput, CompileCache, CompileCacheStats, SourceGraphError, analyze_source,
};
use pine_ir::{HirStmtKind, PersistenceKind, VarSlotId};
use pine_syntax::SourceFile;

fn analyze(text: &str) -> Analysis {
    analyze_source(&SourceFile::new("test.pine", text))
}

mod compatibility;
mod constant_call_semantics;
mod history_constant_calls;
mod lowering;
mod methods;
mod scopes;
mod type_arrays;
mod type_core;
mod type_inputs_outputs;
mod type_ta;
mod user_types;
