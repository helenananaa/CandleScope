use std::env;
use std::path::PathBuf;

use wasm_bindgen_cli_support::Bindgen;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let mut args = env::args_os().skip(1);
    let input = PathBuf::from(
        args.next()
            .ok_or("usage: generate_node_bindings <input.wasm> <output-dir>")?,
    );
    let output = PathBuf::from(
        args.next()
            .ok_or("usage: generate_node_bindings <input.wasm> <output-dir>")?,
    );
    if args.next().is_some() {
        return Err("usage: generate_node_bindings <input.wasm> <output-dir>".into());
    }

    let mut bindgen = Bindgen::new();
    bindgen.input_path(&input).nodejs(true)?.generate(&output)?;
    Ok(())
}
