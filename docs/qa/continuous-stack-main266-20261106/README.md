# Persistent strategy stack on actual main #266

Eleven dependency layers (#251–260/#262) now include actual main `7acba72e56dfafd3a25ee4ec861509f4e9dc6f96`, including #264 imported multi-market BAR replay and #266 narrow-pane legend correction. All integrations were conflict-free. Original checked-out refs and all 3,044 dirty files across 33 other worktrees remain unchanged. No CI was awaited for development; all PRs remain Draft.

## Per-layer evidence

Each backend-changing layer ran every continuous suite present at that layer plus its feature-specific cases. The bottom layer additionally tested imported multi-market/local-data APIs. Frontend-changing layers ran their own changed tests through the canonical Monaco/tsx loader. These are **focused** checks, not the earlier larger full combinations. Counts are overlapping and must not be added.

|PR|Focused tested source|Actual-main ancestry head|Backend passed|Frontend passed|
|---|---|---|---:|---:|
|#251|`d07460cec077`|`55a41616279f`|203|unchanged|
|#252|`0c10c71ba3ac`|`1905c82ee832`|204|unchanged|
|#253|`cf1ee45d1f36`|`7c598fd9bd6f`|224|unchanged|
|#254|`72d1dfe5c132`|`33f8568b5044`|225|26|
|#255|`ec45a59f4277`|`703963ba885d`|262|unchanged|
|#256|`0644567ef492`|`b6844c8d9849`|283|unchanged|
|#257|`c768b04fa43f`|`07f93186f668`|266|16|
|#258|`460b9b50af95`|`4247046b6ad8`|inherited|6|
|#259|`037fbbc5367e`|`4694b4a34895`|inherited|2|
|#260|`96c31e177922`|`3add04e46c51`|inherited|5|
|#262|`7917872ee5a2`|`e7821d763c4f`|274|14|

The focused tests originally included reviewed #266 head147f plus main05a. After #266 merged, actual main7ac was merged through the chain. Entire `backend`, `frontend`, `packages` and `.github` trees matched each corresponding focused-tested source exactly; those results are explicitly inherited by tree identity. The actual-main merge-relationship logs and tree IDs are retained. There was no forced ref rewrite. UI-only layers inherited an identical backend from their direct dependency.

## Fresh top-level qualification

All following current checks belong to top source **`e7821d763c4faa97f38722acc6bae1a78043b006`**. They are not relabelled as a full test run on lower layers. A later QA-only commit can reuse the same product/test trees.

- Backend: **565 passed, two Windows-specific skips, five existing warnings**, one run of 46 suites: persistent execution/results/API/repair, Python editor/runtime, accounting/checkpoint/rollback, source fencing, imported multi-market BAR, local-offline boundaries and replay notes. The skipped AppContainer/ACL cases do not establish Windows qualification. Pine tests use the explicitly isolated source runner, current repository Python bridges/SDK and retained compiled core; they are not installed Pine Native acceptance.
- `npm run check`: architecture, plugins, i18n, both TypeScript configs, lint, **4,943 regular tests, one separate performance test, 130 desktop tests**, all passed with zero frontend skips, followed by production build. Existing lint and bundle-size warnings remain.
- Backend static architecture: same ten findings as an independently reconstructed actual-main baseline, using 895 verified main Python Git blobs. This is not architecture-clean.

## Actual browser flow

The unchanged server/browser fixtures and production API, SQLite, Python subprocess, Host, front-end workspace/draft controls and DataManager passed all four stages. Only local deterministic BAR/stream leases are fixture inputs. The selected frozen program and settings apply solely to explicitly chosen cell2; cell1 and the original research row stay unchanged. Fresh Python permission and explicit initialization create one new account with capital5000,20% sizing,3.5bps fee/2bps slippage; committed events advance20→25. Rendered equity `5004.938134334740712671031105` and position `1.998899864451675630769230768` agree with a separate Decimal valuation from the committed quote balance, position quantity and mark. Renderer reload retains the draft/run25, leaves Python permission unconfirmed, and makes no duplicate creation. No page errors occurred. Browser/server exited0, owned Vite exited onSIGINT(-2); all15 observed owned PIDs were independently absent, controller closed, leases empty and research unchanged.

This is an actual browser/component composition flow, not a packaged research-to-chart or public feed qualification. The new fresh-label harness passed on its first run; older warmup failures remain at their original evidence paths.

## Current installed Native cold-reader qualification

A fresh local arm64 candidate reused the verified previous runtime/plugins, replaced current tracked backend/SDKs and fresh frontend/desktop, updated ASAR integrity and deep ad-hoc signing. It is a local acceptance assembly, not a standalone runtime/release rebuild. **1,076 source files,172 built files,nine plugin assets and76 plugin source files matched; zero differences and strict deep signature passed before/after.**

The packaged app passed **11 stages** using a fresh LOCAL_OFFLINE profile containing a copy of the previously exited synthetic saved account. The original122 profile files stayed byte-identical. It opened the actual saved-account dialog without data/chart/editor creation, showed equity10003,position1,25events and REPAIR_REQUIRED after a committed repair, and exposed no execution/repair controls. Normal full exit, immutable cold SQLite witness, same-profile restart and second normal full exit preserved the exact complete account/definition/checkpoint SHA `779de17a7cafacec0f0e90743ce29816bce8ffc697e3b37d8e535bec7e3b922c`. All ten observed owned PIDs were independently absent. Health checks reported installed offline guard and zero blocked attempts; captured URLs were loopback-only, no account mutation or renderer error occurred. The restart screenshot was visually inspected.

This narrowly qualifies the read-only saved-account entry. **Current-source Native initialization/execution, live gap/restart repair and selected research-to-chart Native execution are still unqualified**, as are Windows/public-market and full #157/#158. Existing earlier-source results remain attributed to their original sources.

## Storage and reproduction

Only completed synthetic #223/#218 pytest/runtime-in-test/architecture fixtures under two owned `/tmp/candlescope-*-main265-20261106` roots were deleted. No open handle or incoming workspace symlink was found.42 raw evidence files stayed unchanged; source/tests and retained commands regenerate those fixtures. Removed logical bytes892180976; observed free-space delta917426176 bytes, which may include concurrent filesystem activity and is not an APFS allocation claim. Apps, Native profiles, original source/dirty files and prior rollback artifacts remain retained.

`receipt.json` hashes every archived artifact; gzip payloads were round-tripped byte-for-byte. No database, user profile or app is committed. Source fingerprints cover the exact source/test/build configuration bytes; they are actual working bytes (tracked CRLF examples can differ from Git LF blobs). Full commands/environments are in `full-checks.json.gz`; per-layer commands are in `layer-results.json.gz`. Reproduction helpers preserve the fixed checkout and require a fresh output/profile label. Native assembly and cold-reader helpers are the unchanged files under `docs/qa/continuous-stack-native-main261-20261106`; use a fresh candidate/profile and the retained source-verified runtime, never overwrite previous evidence.

Current live inventory remains46open issues and15Draft PRs after #266 merge. Next priorities are source-specific LIVE Native gates for #227/#223/#218/#249 after the existing exchange cooldown, then persistent execution/repair qualification; additional offline work continues independently. Any merge to main requires another final-head/current-base/applicable-CI/product-proof audit.
