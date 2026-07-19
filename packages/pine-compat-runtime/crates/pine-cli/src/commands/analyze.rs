use pine_sema::analyze_input;
use pine_syntax::Severity;

use crate::library_sources::{
    LibrarySourceSpec, analysis_input_from_paths, parse_library_source_spec,
};
use crate::usage;

pub(crate) fn run(args: Vec<String>) -> Result<(), String> {
    let options = parse_options(&args)?;
    let input = analysis_input_from_paths(&options.path, &options.library_sources)?;
    let source = input.root().clone();
    let analysis = analyze_input(&input);
    println!("diagnostics: {}", analysis.diagnostics.len());
    println!(
        "supported: {}, unsupported: {}",
        analysis.compatibility.supported.len(),
        analysis.compatibility.unsupported.len()
    );
    let has_errors = analysis
        .diagnostics
        .iter()
        .any(|diagnostic| diagnostic.severity == Severity::Error);
    for diagnostic in analysis.diagnostics {
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
    if has_errors {
        return Err("analysis failed".to_owned());
    }
    Ok(())
}

#[derive(Debug)]
struct AnalyzeOptions {
    path: String,
    library_sources: Vec<LibrarySourceSpec>,
}

fn parse_options(args: &[String]) -> Result<AnalyzeOptions, String> {
    let Some(path) = args.first() else {
        return Err(usage());
    };
    let mut options = AnalyzeOptions {
        path: path.clone(),
        library_sources: Vec::new(),
    };
    let mut index = 1;
    while index < args.len() {
        match args[index].as_str() {
            "--library-source" => {
                index += 1;
                let Some(value) = args.get(index) else {
                    return Err(usage());
                };
                options
                    .library_sources
                    .push(parse_library_source_spec(value)?);
            }
            _ => return Err(usage()),
        }
        index += 1;
    }
    Ok(options)
}

#[cfg(test)]
mod tests {
    use super::run;
    use std::{env, fs};

    #[test]
    fn analyze_returns_error_when_error_diagnostics_exist() {
        let path = env::temp_dir().join(format!(
            "pine_analyze_error_{}_{}.pine",
            std::process::id(),
            line!()
        ));
        fs::write(&path, "indicator(\"bad\")\nplot(unknown)\n").expect("write script");

        let result = run(vec![path.to_string_lossy().into_owned()]);

        fs::remove_file(&path).expect("remove script");
        assert_eq!(result, Err("analysis failed".to_owned()));
    }
}
