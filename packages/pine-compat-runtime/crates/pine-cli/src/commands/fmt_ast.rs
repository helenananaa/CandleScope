use std::fs;

use pine_syntax::{SourceFile, parse_source};

use crate::usage;

pub(crate) fn run(args: Vec<String>) -> Result<(), String> {
    let [path] = args.as_slice() else {
        return Err(usage());
    };
    let text = fs::read_to_string(path).map_err(|err| format!("failed to read {path}: {err}"))?;
    let source = SourceFile::new(path, text);
    let parsed = parse_source(&source);
    println!("{:#?}", parsed.program);
    for diagnostic in parsed.diagnostics {
        let line_col = source.line_col(diagnostic.span.start);
        println!(
            "{}:{:?}:{}:{}: {}",
            diagnostic.code,
            diagnostic.severity,
            line_col.line,
            line_col.column,
            diagnostic.message
        );
    }
    Ok(())
}
