# Official replay catalog shutdown ownership

Product source `fb4cba41a203ecbc7ebbdcf02f41f407ed7600d3`, based on actual main `7acba72e56dfafd3a25ee4ec861509f4e9dc6f96`. The change is independent of pending PRs #227 and #267.

LIVE shutdown previously cancelled the asynchronous catalog waiter while urllib TLS and the catalog executor kept running. An actual no-Pine Native diagnostic on the earlier indicator candidate retained 16 TLS thread stacks and a 15-second SIGKILL request (see PR #227's real-bus diagnosis). A new local stalled-TLS counterexample on unmodified main reproduced physical catalog work surviving runtime/lease release; its original failing log is retained.

The runtime now owns cancellable aiohttp listing requests through the existing canonical synchronous S3 parsers. It closes/drains actual requests, then drains physical catalog/parser/publication threads before service and archive-lease release. Metadata pruning is also drained. Repeated/concurrent shutdown calls share an owner; failed cleanup retains references for retry and caller cancellation remains observable. At most 16 markets are admitted at once; discovery still covers all symbols. Atomic generation publication, validated offline cache, page/byte limits and the configured timeout remain in place. No new dependency, subprocess catalog, trading logic, symbol whitelist or altered desktop shutdown deadline.

## Component and integration evidence

Six new cases cover stalled TLS, a stalled HTTP body, discovery-phase cancellation, repeated cancellation during metadata pruning and generation publication, and real local HTTP pagination (40 historical symbols, 82 requests). Shutdown waits for physical work; queued markets are not admitted; existing catalog/index identities remain byte-for-byte intact, no false discovery marker is written, and catalog threads are absent. A cold pytest interpreter returned normally.

The single 27-suite backend invocation reports **306 passed, 2 failed, 1 skipped, 4 warnings**. Both failures are unchanged 5m/15m trade-bar parity tests: an isolated Git archive of actual main reproduces exactly the same **2 failed / 6 passed**. Do not call the combined check green. The one skipped Windows CRT descriptor case is not Windows acceptance. Static architecture output is exactly main's existing 10 violations; pending #267 is not included. The initial broad invocation omitted the basetemp parent and failed fixture setup; that original output is retained, and the corrected invocation creates its parent explicitly.

## Actual macOS evidence

A physical, source-resolving APFS clone of the qualified #267 runtime received the complete current tracked backend (949 files), compilation and a new strict ad-hoc signature. Frontend/packages Git trees equal that candidate, its complete ASAR SHA-256 and all nine plugin resources remain identical, and unchanged SDK bytes are verified. This is a local reused-runtime candidate, without a fresh frontend or standalone release build.

The confirmed run launched actual LIVE macOS Electron twice with a new QA profile, observed active official discovery on both launches, configured and saved a BTCUSDT chart without Pine, quit, reopened the same profile, then quit again. Exact observed sidecars returned **0 / null signal** twice with **no kill requests**; app-close elapsed times were **2251 ms / 11824 ms**. All 20 captured app-owned PID entries were independently absent afterward; source fingerprints and strict signature still matched, with no page errors. The restart window diagnostic is retained, but it was sampled before bars finished loading; this is not qualification of restored chart data or of live input freshness. Neither public catalog synchronization nor downloaded trade bodies completed in these brief runs.

The first Native wrapper called a nonexistent `ControlClient.close()` after successfully saving the workspace. Its original failure is retained; its cleanup independently returned sidecar 0 with no kill request and all ten PIDs absent. The corrected confirmed run is separate. There is no change to original Native assertions or desktop kill behavior.

This evidence qualifies catalog cancellation/shutdown on the tested macOS candidate only. It does not qualify live Pine updates, replay financial outcomes, full public-market discovery/download, Windows, or a release installer. PR #227 remains Draft with its own source/native limitations.

## Preservation and delivery

All 33 original worktrees, 3044 dirty files and original refs/statuses remain unchanged. Candidate apps, profiles, recovery artifacts and raw failure evidence are retained. Only proven reproducible temporary test/source fixtures may be removed under a separate cleanup receipt. CI runs in the background; a main merge needs a fresh audit of exact head, actual main and applicable checks.

[`receipt.json`](receipt.json) indexes SHA-256-verified compressed raw evidence and exact commands.
