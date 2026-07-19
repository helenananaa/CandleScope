# Contributing

This project is a clean-room Pine-compatible indicator runtime.

## Rules

- Do not copy TradingView source code, private APIs, proprietary data, UI, icons,
  branding, or error text.
- Prefer original fixtures written for this project.
- Include license and source metadata for non-original fixtures.
- Unsupported language behavior must produce diagnostics instead of panics.
- Keep host-specific adapters outside the core runtime crates.

## Development

Before submitting changes, run:

```bash
cargo fmt --check
cargo clippy --workspace --all-targets -- -D warnings
cargo test --workspace
python3 scripts/check_structure.py
cargo check -p pine-wasm --target wasm32-unknown-unknown
```

Python binding changes should also be checked in an active virtual environment
where the extension module can be installed:

```bash
python -m pip install --upgrade pip maturin pytest
maturin develop --manifest-path crates/pine-python/Cargo.toml
python -m pytest python/tests
```

## Module Ownership

New code should go to the crate and module that owns the behavior:

- `pine-syntax`: source files, lexer, parser, AST, and syntax diagnostics.
- `pine-builtins`: semantic signatures, built-in constants, namespace registry
  data, and shared return specifications.
- `pine-sema`: compatibility reports, resolver/scope rules, type acceptance,
  call validation, HIR lowering, and semantic history requirements.
- `pine-runtime`: bar execution, runtime values/storage, built-in execution,
  output collection, profiling, retention, and realtime update behavior.
- `pine-cli`, `pine-python`, and `pine-wasm`: thin host adapters only.

Built-in additions must move through all applicable owners in one change:

- semantic signature or constant metadata in `pine-builtins`
- type, argument, or unsupported-feature validation in `pine-sema` when needed
- runtime implementation in `pine-runtime`
- fixture coverage under `tests/fixtures`
- conformance metadata in `tests/fixtures/conformance.tsv` when capability
  reporting changes

Keep cross-crate behavior fixtures in `tests/fixtures`. Keep small edge-case
tests near the module that owns private helper behavior.

## Source Size Guardrail

`python3 scripts/check_structure.py` checks production Rust source files before
the binding checks in `scripts/verify.sh`. The default limits are:

- Facade files such as crate-root `lib.rs` and declaration-only `mod.rs`: 300
  lines.
- Model/helper modules: 800 lines.
- Implementation modules: 1,500 lines.

Large table-heavy files must be listed in the script allowlist with an owner,
reason, and split plan. Do not widen production visibility just to move tests;
prefer module-local tests, `pub(super)`, or `pub(crate)` only when there is a
real internal API boundary.
