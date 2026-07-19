use std::{env, process::ExitCode};

mod bars_csv;
mod commands;
mod conformance;
#[cfg(test)]
mod drawing_signature_contract_tests;
mod json;
mod library_sources;
#[cfg(test)]
mod object_cast_contract_tests;
#[cfg(test)]
mod runtime_snapshots;

fn main() -> ExitCode {
    match run() {
        Ok(()) => ExitCode::SUCCESS,
        Err(message) => {
            eprintln!("{message}");
            ExitCode::FAILURE
        }
    }
}

fn run() -> Result<(), String> {
    let mut args = env::args().skip(1);
    let Some(command) = args.next() else {
        return Err(usage());
    };

    match command.as_str() {
        "analyze" => commands::analyze::run(args.collect()),
        "fmt-ast" => commands::fmt_ast::run(args.collect()),
        "run" => commands::run::run(args.collect()),
        "matrix" => commands::matrix::run(args.collect()),
        _ => Err(usage()),
    }
}

pub(crate) fn usage() -> String {
    "usage: pine-compat analyze <script.pine> [--library-source KEY=path.pine]...\n       pine-compat fmt-ast <script.pine>\n       pine-compat run <script.pine> --bars <bars.csv> [--library-source KEY=path.pine]... [--request-bars SYMBOL:TIMEFRAME=bars.csv]... [--input-override CALL_SITE_ID=value]... [--profile]\n       pine-compat run <script.pine> --bars <bars.csv> --render-strategy-order-alert-template <template> --strategy-alert-index <index>\n       pine-compat run <script.pine> --bars <bars.csv> --render-strategy-running-alert <template> --strategy-alert-index <index> --running-alert-script-snapshot-id <id> --running-alert-symbol <symbol> --running-alert-timeframe <timeframe>\n       pine-compat matrix [--format text|json]".to_owned()
}

#[cfg(test)]
mod main_tests;
