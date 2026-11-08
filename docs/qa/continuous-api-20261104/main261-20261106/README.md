# Continuous API on current main261

Source `9e58c03aff5d57efce1dedb6b7c5e93f0a68412d` merges current #252 head
`b8e93f360b201f8c6d089ee2a003fd6c7e24b307` into prior
`c7b5d50d9b5ed65087e18bd31f710aac3fe3f5f9` with no conflicts. This keeps actual main261
`0de39f37f2389b09a35fc91e3a6d8d5844137da8` in the dependency ancestry. The API layer itself
is unchanged by the main propagation; no new scope or compatibility fallback.

Single combined regression: **373 passed / 2 Windows-only skips / 5 existing
warnings**. Coverage includes actual FastAPI HTTP/WS, ordered creation/control
and read identities, bounded result pages, source/account/definition isolation,
Manager/default profile lifecycle, actual Python processes and financial/
transaction/accounting/source tests. The two skips are existing Windows
AppContainer and ACL lifecycle cases, not macOS regressions or Windows passes.
The precise source fingerprints/launcher/repository SDK paths/test list and
isolated environment are in source-manifest.json. No public feed or user
profile is used. The10 architecture findings remain byte-equal to main261.

Previous source/API/browser/Native evidence retains its own revision/scope. This
does not qualify current installed packages, full Native quit/restart, Windows,
live exchange behavior or later repair/research layers. New CI runs in the
background; only a main merge needs final-head/current-base applicable checks.
Next propagate into #254 UI and the later repair/saved-reader/selected-version
chain; do not retarget a top-only merge in a way that inflates the stacked diff.
