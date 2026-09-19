# Pine 0.3 adapter qualification

Date: 2026-09-12. Local Windows AMD64, CPython 3.12.

## Identity

- Bridge: `candlescope-plugin-pine-compat==0.3.0.dev1`.
- SDK: `candlescope-plugin-sdk==0.2.0`.
- Engine: `pine-compat-runtime==0.3.0rc1`, compiled with `maturin build
  --release --locked` from clean detached commit
  `a481b4644c142badcf9e1bc5430bc3a5f7f2a733` in
  `E:/projects/pine-candlescope-adapter-20260912`.
- Engine wheel SHA-256:
  `da4523dabf08f39211c38ba8b8b6ff9e48f22f0e618058cb9df9ba307a4fa621`.
- Final CSPKG SHA-256:
  `ddf0f10e27f4541cf544c631537584c429974249d94291c4dba454e8c7f242aa`.

The candidate lock pins all three wheel hashes and the source commit. The old
public release lock is historical. No existing runtime registry was switched.
The independent interpreter's uncommitted gradient-fill work was excluded.

## Implemented

- Version and schema checks select the 0.3 engine and streaming contracts.
- Native indicator sessions accept a trailing forming bar, replacements,
  confirmation and append. WebSocket identities isolate subscriptions; HTTP
  range requests do not mutate those sessions.
- History/source/parameter changes and LRU misses replay history explicitly.
  Failed multi-bar or output conversion work invalidates retained state.
- Native host requirements are returned in analysis metadata.
- The backend demonstration strategy rejects modified or arbitrary sources,
  preventing their accidental execution with its fixed threshold.

## Verification

- Engine: 758 tests against the installed newly built wheel, from the frozen
  checkout's `python/tests`.
- Bridge: 18 source tests; 10 installed runtime/session tests with pytest
  `-o pythonpath=` to disable source-path injection.
- Backend: 38 tests across Pine strategy, strategy workspace, subscription
  identity, runtime routing and runtime service suites.
- Installer `install()` and `check()` passed in an isolated managed root.
- A real `RuntimeSupervisor` launched the installed sidecar and verified SMA
  values during forming replacement and confirmation, including retained
  session metadata. Isolated `python -I` imports resolved inside the managed
  installation for both engine and bridge.
- Ruff passed for the adapter package, scripts, tests and changed backend files.
  Scoped `git diff --check` passed.

## Artifacts and reproduction

Repository-relative `.local/pine-upgrade-20260912/` contains:

- `wheels/`: exact three wheels selected by the candidate lock.
- `candlescope-pine-0.3.0.dev1-win_amd64.cspkg`.
- `installation-check.json`: final installation, probe and import receipt.
- `qualify.py`: builds the candidate lock/package and runs isolated installation
  and sidecar checks. Invoke using the qualification venv with installed wheels.

To rebuild a package from the retained wheels, run the package's
`scripts/build_bundle.py` with `--lock release/release-lock.candidate.json`, the
three `--wheel` paths, and `--output`. The default lock still describes v0.2.0.

## Boundaries

This is a local candidate, with no publication, commit or production activation.
External request data/providers, libraries, arbitrary native strategies and
unmapped drawing families remain rejected. The strategy change is an admission
repair, not a native broker integration.

Sessions retain full input/output history up to the request limits and use an
eight-entry LRU. Eviction, window changes and restart reseed history and cannot
recover prior intrabar/varip state. `sessionReset` exposes that boundary. There
is no new long-duration, concurrency, Linux, WASM or browser UI qualification.
The wire response remains a full Render IR snapshot rather than native deltas.
