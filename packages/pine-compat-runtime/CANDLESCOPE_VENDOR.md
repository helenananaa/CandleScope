# CandleScope vendored package

This directory is based on the source snapshot of
[`Ryan00956/pine-compat-runtime`](https://github.com/Ryan00956/pine-compat-runtime)
at commit `cec39d807a469ebae199f30bc67a91d7081a3b9f` (package version `0.2.0`).
It also carries CandleScope-side forward patches for deterministic local
dataset endpoints and the versioned native realtime-session ABI. Those patches
are not present in the public v0.2.0 wheel selected by the managed lock below.

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
the pinned `v0.2.0` manifest, verifies the manifest and wheel SHA-256 digests,
installs the matching Windows x86-64 or manylinux x86-64 wheel into
`backend/.venv`, and runs the Pine-specific schema/SMA probe:

```powershell
cd backend
.\setup.ps1
```

The `v0.2.0` Release tag and this vendored source snapshot both point to commit
`cec39d807a469ebae199f30bc67a91d7081a3b9f`; the forward patches described
above are repository-local until a newer runtime release is published and the
verified manifest/digest lock is advanced. CandleScope host integration and
installation code remains outside the runtime package.

Once that newer Release has published both required wheels and its exact
manifest, prepare—but do not silently apply—the next CandleScope lock with:

```powershell
backend\.venv\Scripts\python.exe backend\scripts\prepare_pine_runtime_release.py `
  --manifest <release-assets>\manifest.json `
  --assets-dir <release-assets>

# Repeat with --write only after reviewing the rendered lock.
```

The preparation step requires the Windows and manylinux `cp310-abi3` wheels,
checks their embedded package metadata, size, and SHA-256, binds the full source
commit and Release identity, and selects the `pine-runtime-v2` probe. That probe
executes seed/forming/confirmed transitions to prove the realtime ABI rather
than trusting exported constants alone. A failed upgrade can restore only a
same-identity, hash-matching cached predecessor; otherwise installation fails
closed.

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
