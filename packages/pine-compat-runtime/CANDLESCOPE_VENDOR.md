# CandleScope vendored package

This directory is a source snapshot of
[`Ryan00956/pine-compat-runtime`](https://github.com/Ryan00956/pine-compat-runtime)
at commit `d0aa4af0e7e2f4c812b771c6ccd9c028169bad7a` (package version `0.1.0`).

CandleScope treats this package as a sibling of `packages/pyne-runtime`. The
backend integration lives outside this directory under
`backend/app/indicator/runtimes`, so upstream source stays independently
buildable and replaceable.

The snapshot contains the build manifests, license, Rust crates, and package
documentation. Upstream CI files, generated build output, helper scripts, and
the large repository-level fixture/test corpus are intentionally excluded from
the application vendor snapshot. Crate-local test source remains present;
`pine-python` is self-contained and validated here, while `pine-cli` and
`pine-wasm` test targets require the omitted upstream repository fixtures.

Normal CandleScope setup does not compile this package. The managed plugin
registry selects the backward-compatible `CANDLESCOPE_RUNTIME.json` lock; the
generic loader adapts it to the shared `python-wheel` driver, which downloads
the pinned `v0.1.0` manifest, verifies the manifest and wheel SHA-256 digests,
installs the matching Windows x86-64 or manylinux x86-64 wheel into
`backend/.venv`, and runs the Pine-specific schema/SMA probe:

```powershell
cd backend
.\setup.ps1
```

The Release tag points to commit
`e01b756f6d70256d80903952df3022391b7d3dcf`. It is four commits after the
vendored source commit above; those commits add release automation,
documentation, and tests without changing the runtime crates.

Developers can still build and install a local wheel explicitly:

```powershell
cd packages/pine-compat-runtime
maturin build --release --locked
python -m pip install --force-reinstall target/wheels/pine_compat_runtime-*.whl
```

The extension uses PyO3 `abi3-py310`; a wheel built for the target operating
system and architecture can be used by supported CPython versions from 3.10
onward. CandleScope loads `pine_compat` lazily and reports Pine as unavailable
until a compatible wheel is installed.
