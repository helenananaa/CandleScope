# Pine output candidate on main250

Source b784fb52f8955fedb7aaa93015a543b0db593b4b integrates main18cd6f34
without conflicts. Frontend/packages product bytes match prior a7593c5d.
All 39 pre-existing local QA files retain their exact SHA256 values; none was
staged or overwritten. The independent assembly helper verifies the existing
Pine plugin's source bytes and engine pin before reuse.

Current backend regressions: **59 passed / 5 warnings / zero skips**, covering
real patched/full Pine sidecar comparisons and restart, indicator service/routes,
and main250 Controller ownership. The dedicated copies-venv preserves its own
launcher and read-only qualified core 0.3.3+cs.1; production child environment
isolation remains unchanged. This is not a full backend/frontend suite.

A fresh APFS clone of the retained output-main243-depth candidate contains current
tracked backend and SDK mirrors, unchanged verified frontend/desktop and the
source-verified existing Pine plugin. 1054 source/SDK files,164 frontend assets,
9 plugin assets and76 plugin source files match; strict signing verification
passes. This is a local arm64 candidate, not a fresh standalone runtime build.

The candidate has not launched LIVE yet. Actual negative-offset updates/deletions,
markers/bgcolors, saved source/full owned quit/restart remain pending and will run
after the current Gate owner fully exits and the shared public gate permits it.
Earlier local/CI/Native records stay separate. Entire #152, Windows and O(N)
materialization remain open. CI runs in the background; main merge requires exact
final head/current base checks and applicable Native evidence.
