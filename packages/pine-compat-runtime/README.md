# Pine Compat Runtime

**Run Pine-style indicators and strategies on your own market data — locally,
deterministically, and from the host you already use.**

[![Latest release](https://img.shields.io/github/v/release/Ryan00956/pine-compat-runtime?display_name=tag&sort=semver)](https://github.com/Ryan00956/pine-compat-runtime/releases/latest)
[![CI](https://github.com/Ryan00956/pine-compat-runtime/actions/workflows/ci.yml/badge.svg)](https://github.com/Ryan00956/pine-compat-runtime/actions/workflows/ci.yml)
[![Wheels](https://github.com/Ryan00956/pine-compat-runtime/actions/workflows/wheels.yml/badge.svg)](https://github.com/Ryan00956/pine-compat-runtime/actions/workflows/wheels.yml)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://github.com/Ryan00956/pine-compat-runtime/releases/latest)
[![Rust 1.95+](https://img.shields.io/badge/Rust-1.95%2B-000000?logo=rust&logoColor=white)](Cargo.toml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Pine Compat Runtime is a clean-room, open-source runtime for an executable
Pine-compatible subset. Feed it source code and OHLCV bars; get structured,
host-neutral results for plots, drawings, alerts, orders, trades, positions,
and equity.

It is built for charting products, research tools, notebooks, backtesting
workflows, and anyone who wants Pine-style execution without coupling their
application to a charting service.

> [!NOTE]
> This project is not affiliated with, endorsed by, or sponsored by
> TradingView. It implements a tested compatibility subset and does not claim
> full Pine Script compatibility.

## Why Pine Compat Runtime?

- **Bring your own data.** Run over CSV bars or in-memory OHLCV records. The
  core does not fetch symbols, read host files, or make network requests.
- **Embed it anywhere.** Use the Rust core, CLI, Python extension, or thin WASM
  API without reimplementing Pine execution semantics in your host.
- **Get useful output, not screenshots.** Results are versioned, JSON-ready
  structures that a chart, notebook, API, or test suite can consume directly.
- **Model time series correctly.** Historical references, persistent state,
  stateful call sites, incremental append, and realtime forming-bar rollback
  are runtime concepts rather than host-side approximations.
- **Know what will run.** Unsupported features become source-spanned
  diagnostics and compatibility reports instead of silent partial execution.
- **Trust claims you can test.** The compatibility matrix is backed by
  executable fixtures, cross-host parity checks, and a single release gate.

## Quick Start

Version `0.2.0` ships ready-to-install Python wheels for CPython 3.10+ on
glibc Linux x86-64 and Windows x86-64. See the
[latest release](https://github.com/Ryan00956/pine-compat-runtime/releases/latest)
for checksums and machine-readable release metadata.

Linux x86-64:

```bash
python -m pip install \
  "https://github.com/Ryan00956/pine-compat-runtime/releases/download/v0.2.0/pine_compat_runtime-0.2.0-cp310-abi3-manylinux_2_17_x86_64.manylinux2014_x86_64.whl"
```

Windows x86-64:

```powershell
py -m pip install "https://github.com/Ryan00956/pine-compat-runtime/releases/download/v0.2.0/pine_compat_runtime-0.2.0-cp310-abi3-win_amd64.whl"
```

Then run an indicator directly from Python:

```python
import pine_compat

source = """//@version=6
indicator("SMA demo")
avg = ta.sma(close, 3)
plot(avg, "SMA 3")
"""

bars = [
    {"time": i, "open": close, "high": close, "low": close,
     "close": close, "volume": 100.0}
    for i, close in enumerate([10.0, 11.0, 12.0, 13.0])
]

result = pine_compat.run_script(source, bars)
print(result["plots"][0]["values"])
# [None, None, 11.0, 12.0]
```

That same result can include chart annotations, drawing snapshots, alerts, and
partial strategy broker output — all without requiring a chart UI.

## What Works Today

The current release focuses on a broad indicator runtime and a deliberately
bounded strategy runtime.

| Area | Current executable subset |
| --- | --- |
| Language | fixture-backed v1-v6 declarations, series and history, bounded v1/v2 declaration graphs, `var`/partial `varip`, functions, tuples, `if`, `switch`, partial `for`/`while`, strings, UDTs, and host-provided pure library imports |
| Indicators | Common `ta.*`, selected `math.*`/`str.*`, inputs, plots, colors, alerts, drawing objects, tables, typed collections, fixture-backed `request.security`, and the documented executable Pine v1-v4 legacy-indicator subsets including `security` |
| Execution | Deterministic historical runs, guarded history, input overrides, incremental append, and realtime forming-bar rollback |
| Strategies | Partial long-only entries, orders, closes, cancellations, stop/limit/bracket/trailing exits, quantity reservations, positions, trades, and equity snapshots |
| Outputs | Versioned plots, shapes, bars, candles, fills, labels, lines, line fills, polylines, boxes, tables, alerts, diagnostics, and strategy results |
| Hosts | Rust workspace, `pine-compat` CLI, `pine_compat` Python module, and `wasm-bindgen` API |

Legacy indicator compatibility is released by source version, not as one broad
backwards-compatibility promise:

| Source profile | Maturity | Current claim |
| --- | --- | --- |
| Pine v4 indicators | Preview | Direct execution for the conformance-listed declaration, input, alias, output, expression, session, and `security` subsets |
| Pine v3 indicators | Preview | Direct execution for the conformance-listed pre-v4 declaration, input/output, alias, metadata, `na`, and same-context `security` subsets |
| Pine v2 indicators | Experimental | Direct execution for the focused declaration graph, conversion, basic indicator, and historical-lookahead `security` subsets |
| implicit Pine v1 indicators | Experimental | Direct execution for the focused v1/v2 shared `study`/input/average/plot subset |

These labels reflect evidence breadth: the fixed original seed corpus contains
only 12 v4, 7 v3, 2 v2, and 1 v1 eligible indicators. All currently pass, but
none reaches the provisional 50-script stable-profile evidence gate. Legacy
strategies are excluded from every profile.

Support is intentionally feature-specific. Before adopting a script corpus,
use the analyzer or the executable compatibility matrix rather than assuming
language-wide compatibility:

```bash
cargo run -p pine-cli -- matrix
cargo run -p pine-cli -- matrix --format json
```

The matrix in [`tests/fixtures/conformance.tsv`](tests/fixtures/conformance.tsv)
and its referenced fixtures are the source of truth. See
[Language Scope](docs/LANGUAGE_SCOPE.md) for the detailed boundary and
[Conformance](docs/CONFORMANCE.md) for how claims are accepted.

## Choose Your Integration

| Surface | Best for | Entry point |
| --- | --- | --- |
| Python | notebooks, research services, data pipelines, application plugins | `pine_compat.run_script(...)` or compile once with `compile_script(...)` |
| CLI | shell workflows, fixtures, compatibility checks, JSON generation | `pine-compat run`, `analyze`, `fmt-ast`, and `matrix` |
| Rust | native applications and deeper runtime embedding | workspace crates under [`crates/`](crates) |
| WASM | browser, Node.js, and sandboxed JavaScript hosts | `compileScript`, `analyzeScript`, `runScriptCsv`, and `Program.runCsv` |

### Python

Compile once and reuse a program across data sets or input configurations:

```python
import pine_compat

source = '''//@version=6
indicator("Configurable SMA")
length = input.int(20, "Length")
plot(ta.sma(close, length))
'''

report = pine_compat.analyze_script(source)
length_id = report["inputs"][0]["callSiteId"]
program = pine_compat.compile_script(source)

result = program.run(bars, input_overrides={length_id: 50})
```

Python can also inject deterministic requested bars and exact-key library
sources:

```python
result = pine_compat.run_script(
    source,
    bars,
    request_bars={"NYSE:IBM:5": requested_bars},
    library_sources={"user/lib/1": library_source},
    chart_symbol="NASDAQ:AAPL",
    chart_timeframe="1",
)
```

Legacy indicators use their source version automatically; no host flag is
needed. The same analysis schema reports the selected dialect and any
translation/emulation evidence before execution:

```python
legacy = '''//@version=4
study("Legacy SMA")
length = input(20, "Length", input.integer)
plot(sma(close, length))
'''
report = pine_compat.analyze_script(legacy)
assert report["dialect"] == "v4" and report["executable"]
result = pine_compat.run_script(legacy, bars)
```

The returned `executable` flag proves that this source is admitted by the
implemented subset; it does not upgrade the whole v4 language profile beyond
preview.

### CLI

Run a script against CSV OHLCV data and receive normalized JSON:

```bash
cargo run --release -p pine-cli -- run \
  tests/fixtures/runtime/macd.pine \
  --bars tests/fixtures/runtime/bars.csv
```

Analyze without executing, or inject host-owned request and library data:

```bash
cargo run -p pine-cli -- analyze script.pine
cargo run -p pine-cli -- analyze script.pine --format json

cargo run -p pine-cli -- run script.pine --bars bars.csv \
  --chart-symbol NASDAQ:AAPL --chart-timeframe 1 \
  --request-bars NYSE:IBM:5=ibm-5m.csv \
  --library-source user/lib/1=lib.pine
```

### WASM

The optional `pine-wasm` crate exposes thin, deterministic bindings for
compile, analysis, CSV execution, request-bar injection, and library-source
injection. Build and exercise the real generated JavaScript module with:

```bash
rustup target add wasm32-unknown-unknown
scripts/check_wasm_node.sh
```

See [Architecture](docs/ARCHITECTURE.md) for the host boundary and
[Execution Semantics](docs/EXECUTION_SEMANTICS.md) for historical and realtime
behavior.

## Honest Compatibility

`0.2.0` is a compatibility-focused second release, not a full drop-in
implementation of every Pine feature. Important current boundaries include:

- the strategy broker model is still a partial, primarily long-only subset;
- `request.*` support is limited and all requested data must be supplied by the
  host;
- library resolution is exact-key and host-provided — there is no remote
  registry lookup;
- collection, drawing, alert, UDT, method, and import support is intentionally
  limited to fixture-backed shapes;
- Pine v4/v3 legacy-indicator profiles are previews and Pine v2/v1 profiles are
  experimental because the authorized release corpus is small and has no
  external reference-output oracle;
- legacy strategies, lower-timeframe legacy `security`, and unsupported
  whole-program `study(resolution=...)` execution remain out of scope;
- unsupported syntax or semantics are rejected with diagnostics rather than
  guessed.

This explicit boundary is part of the product: hosts can inspect compatibility
before execution and decide whether to run, transform, or reject a script.

## Architecture

The runtime is a Rust core with thin host adapters:

```text
Pine source + host-provided data
              │
              ▼
 lexer → parser → semantic analysis → HIR → bar-by-bar runtime
              │                              │
              ├─ diagnostics                 ├─ plots and drawings
              └─ compatibility report        └─ alerts and strategy results
                                             │
                      Rust / CLI / Python / WASM
```

Core crates do not fetch network data, resolve remote libraries, or depend on a
specific chart renderer. Hosts own data access and presentation; the runtime
owns language semantics and normalized output.

## Documentation

- [Documentation Guide](docs/README.md) — where current contracts, roadmaps,
  and historical plans live
- [Language Scope](docs/LANGUAGE_SCOPE.md) — detailed supported and unsupported
  language shapes
- [Built-In Signatures](docs/BUILTIN_SIGNATURES.md) — accepted built-ins and
  argument subsets
- [Execution Semantics](docs/EXECUTION_SEMANTICS.md) — bar, history, state, and
  broker behavior
- [Diagnostic Codes](docs/DIAGNOSTIC_CODES.md) — stable diagnostic reference
- [Release Notes](docs/RELEASE_NOTES.md) — changes in each release
- [Releasing Binary Wheels](docs/RELEASING.md) — wheel matrix, checksums, and
  application update contract
- [Compatibility and Legal Boundaries](docs/COMPATIBILITY_AND_LEGAL.md) —
  clean-room and branding policy

## Build From Source

The workspace requires Rust 1.95+. Python bindings require Python 3.10+ and
`maturin`.

```bash
git clone https://github.com/Ryan00956/pine-compat-runtime.git
cd pine-compat-runtime
cargo build --workspace
```

Build the Python module in an active virtual environment:

```bash
python -m pip install "maturin>=1.13,<2.0" pytest
maturin develop --manifest-path crates/pine-python/Cargo.toml
python -m pytest python/tests
```

Before contributing or publishing, run the canonical release gate:

```bash
scripts/verify.sh
```

It covers Rust formatting, clippy, workspace tests, source-structure and host
parity checks, a real WASM/Node execution smoke, Python wheel build and
reinstall, and Python binding tests. See [Releasing Binary Wheels](docs/RELEASING.md)
for the supported release platforms and artifact contract.

## License

[MIT](LICENSE). Pine Script is a trademark of its respective owner. This
independent clean-room project is not affiliated with TradingView.
