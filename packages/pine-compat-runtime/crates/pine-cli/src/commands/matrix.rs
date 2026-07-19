use pine_runtime::PUBLIC_MATRIX_SCHEMA_VERSION;

use crate::conformance::{MatrixEntry, conformance_entries};
use crate::json::json_escape;
use crate::usage;

pub(crate) fn run(args: Vec<String>) -> Result<(), String> {
    let format = match args.as_slice() {
        [] => MatrixFormat::Text,
        [flag, format] if flag == "--format" && format == "text" => MatrixFormat::Text,
        [flag, format] if flag == "--format" && format == "json" => MatrixFormat::Json,
        _ => return Err(usage()),
    };

    let entries = conformance_entries();
    match format {
        MatrixFormat::Text => println!("{}", matrix_text(&entries)),
        MatrixFormat::Json => println!("{}", matrix_json(&entries)),
    }
    Ok(())
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum MatrixFormat {
    Text,
    Json,
}

pub(crate) fn matrix_text(entries: &[MatrixEntry]) -> String {
    let feature_width = entries
        .iter()
        .map(|entry| entry.feature.len())
        .chain([7])
        .max()
        .unwrap_or(7);
    let status_width = entries
        .iter()
        .map(|entry| entry.status.len())
        .chain([6])
        .max()
        .unwrap_or(6);

    let mut output = String::new();
    output.push_str(&format!(
        "{:<feature_width$}  {:<status_width$}  fixtures  notes\n",
        "feature", "status"
    ));
    output.push_str(&format!(
        "{:-<feature_width$}  {:-<status_width$}  --------  -----\n",
        "", ""
    ));
    for entry in entries {
        output.push_str(&format!(
            "{:<feature_width$}  {:<status_width$}  {}  {}\n",
            entry.feature,
            entry.status,
            entry.fixtures.join(";"),
            entry.notes
        ));
    }
    output
}

pub(crate) fn matrix_json(entries: &[MatrixEntry]) -> String {
    let mut output = format!(
        "{{\"schemaVersion\":{},\"features\":[",
        PUBLIC_MATRIX_SCHEMA_VERSION
    );
    for (index, entry) in entries.iter().enumerate() {
        if index > 0 {
            output.push(',');
        }
        output.push_str("{\"feature\":\"");
        output.push_str(&json_escape(&entry.feature));
        output.push_str("\",\"status\":\"");
        output.push_str(&json_escape(&entry.status));
        output.push_str("\",\"notes\":\"");
        output.push_str(&json_escape(&entry.notes));
        output.push_str("\",\"fixtures\":[");
        for (fixture_index, fixture) in entry.fixtures.iter().enumerate() {
            if fixture_index > 0 {
                output.push(',');
            }
            output.push('"');
            output.push_str(&json_escape(fixture));
            output.push('"');
        }
        output.push_str("]}");
    }
    output.push_str("]}");
    output
}
