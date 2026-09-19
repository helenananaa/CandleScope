# Pyne 0.4.0 adapter qualification

Date: 2026-09-12. Local Windows AMD64, CPython 3.12.

## Candidate identity

- Bridge: `candlescope-plugin-pyne==0.3.0.dev1`.
- Workbench: `candlescope-plugin-pyne-workbench==0.1.1`.
- SDK: `candlescope-plugin-sdk==0.2.0`.
- Engine: official `pyne-runtime==0.4.0` wheel, SHA-256
  `8cd1759ab0e3f77fd635e0e0f38d29a2da28913bb8165888e89788213b32a6c7`.
  Downloaded wheel matches the upstream release's `SHA256SUMS`.
- NumPy: `2.3.3`, CPython 3.12 Windows AMD64 wheel.

`release-lock.candidate.json` selects this engine. The old published
`release-lock.json` and production bootstrap remain unchanged.

## Verified

- Bridge source suite: 37 passed.
- Installed bridge suite: 28 passed, with pytest `-o pythonpath=` disabling
  source-path injection. Covers analysis, batch/rendering, incremental sessions,
  preview isolation, reconnect, restart/reseed, broker correlation, host policy,
  strategy execution and restore.
- Installed workbench suite: 19 passed, also with `-o pythonpath=`.
- Backend Pyne strategy and workbench manifest tests: 4 passed, preloading the
  real 0.4.0 engine so the backend's optional stub was not used.
- Offline wheel dependency resolution and `pip check`: passed.
- Fresh `python -I` checks confirmed all three runtime/adapter/workbench imports
  resolve inside the qualification venv's installed `site-packages`.
- CandleScope `PluginInstaller.install()` and `check()` passed for the final
  candidate bundle in an isolated managed root, including sidecar probes.
- `git diff --check`: passed. Ruff comparison against HEAD found no newly
  introduced diagnostics in changed Python files; existing style diagnostics
  remain, so this is not a claim of a clean package-wide lint baseline.

## Local artifacts

Under repository-relative `output/pyne-040-upgrade/` (ignored build output):

- `wheelhouse/`: bridge, workbench, SDK, official engine and NumPy wheels.
- `candlescope-pyne-0.3.0.dev1-cp312-win_amd64-final.cspkg`, SHA-256
  `976b48b161f6fc16a7b9cc3b9c27c0cc27c9e02e622ebb8c7f06b01a6e11c63b`.
- `installation-check.json`: final installation receipt and import provenance.
- `lint-delta.json`: comparison of changed files against HEAD.

The CSPKG is the script-runtime bridge bundle; the separate workbench wheel was
installed and tested separately. No UI end-to-end or other Python/OS matrix was
run. No production registry was activated, and no commit, push or release was
performed. Restart/reseed is the supported upgrade boundary; old Pyne state
snapshots must not be relabeled as computation semantics 5.
