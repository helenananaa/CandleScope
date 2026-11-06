# Pine application host epoch and full market-hook coverage

Source `036d7bd7e028cbe940f80af823a6f3606c60a2bb`, based on PR #227 head6b8d4578. Production change is only `backend/app/indicator/pine_host.py`; frontend changes are isolated browser fixtures/runner, and backend fixture changes match application startup wiring. No new SDK/Pine core or application frontend build.

## Confirmed defect and fix

The actual application installs PineHostInputs.prepare/release/stop on the runtime service. Earlier component/browser fixtures used the real SDK/core but omitted that preparation layer. prepare overwrote the calculation owner's explicit pineSessionEpoch with the standalone __pineSessionEpoch parameter or default0. A requested full-origin rebuild with unchanged BAR bytes therefore retained the previous runtime instead of resetting it.

A new cold actual SDK/core case with the application prepare hook reproduces the precise Native `INDICATOR_CALCULATION_REBUILD_NOT_APPLIED` before the fix. Preserve an explicit transport owner epoch; use the legacy parameter/default only when absent. Four contract cases preserve legacy behavior and owner priority without mutating caller inputs. Rebuild verification confirms generation/sequence advancement with the counter still500 after an actual same-input reset. Host preparation/release/stop and DataManager access are now wired into real ASGI and browser fixtures too.

**38 focused checks passed. The fresh single76-suite run passed977 checks, one Windows CRT-only skip, five existing warnings, zero failures/errors.** The23 ASGI/Manager/SQLite cases owned24 SDK/core workers; each returned0 and was independently absent afterward, with callbacks/leases/registry/watches zero. No Windows qualification or full152/O(N) claim.

## Browser coverage

New production-minified Chromium fixtures use real useMarketDataRuntime, initial history/window ownership, workspace cache, scheduler, useIndicatorRuntime and actual HTTP/WS/SDK/Pine math. Session configuration and upstream BAR/lease production are controlled. The indicator hook receives no injected ready metadata.

Qualified cases cover500→501, adding1000 older rows after the500-bar domain is already live, explicit origin replacement at1500, and forming1501. The latter passes again with actual application host preparation enabled. Domain/source disposal completes before stopping the backend. Every qualified server/browser root returns0; worker/resource receipts are zero. The original direct-hook isolation/correction/late-response scenario also passes as a runner control on8432. This is component/browser evidence, not Native acceptance.

Initial harness failures are retained: incomplete exchange configuration prevented mounting; a debugger endpoint was not yet ready; an inline stream identity caused fixture resubscriptions; and pre-seeding older rows let the genuine warmup read700 bars, invalidating the fixture's500 expectation. The corrected scenario inserts older rows after the initial domain is live, matching the intended lifecycle. The browser runner now waits for its own debugger and target within its existing launch deadline. A failed browser round also spawned GoogleUpdater daemons; they were identified as external updater processes and not killed or relabelled as application-owned cleanup success.

## Actual macOS observations and remaining failure

A short diagnostic on unchanged6a shows500 initial chart rows, later1500 historical Pine output and a live subscription with clear gates. This contradicts a claim that history readiness is always stuck. It is diagnostic-only, without a six-value/parity/restart claim.

A subsequent original full Native run on6a captures source-read errors followed by `INDICATOR_CALCULATION_REBUILD_NOT_APPLIED`; installed registry and all78 SDK/Pine/core module files match verified wheels byte-for-byte. It fails the original six-distinct-values/parity assertion and exits normally. This led to the application-hook counterexample above.

The new physical macOS candidate clones verified6a resources, changes/compiles only pine_host.py, then receives a fresh strict signature. All1072 source/SDK mirror fingerprints,164 built assets,9 plugin assets and76 plugin-source files match before/after; inherited ASAR remains exact. This is a local reused-runtime candidate, not a release rebuild.

**The current source still fails full Native acceptance.** It records normal old-domain closure and then `Chart calculation input is not contiguous`, loses the live writer, and cannot satisfy six distinct counter updates/both parities. Saving source/restarting assertions are not reached. The epoch error was not recorded in this run, but source rejection precedes full recovery, so this does not qualify the full Native rebuild path. Exact sidecar exits0/signalnull/no kill requests; all ten owned PIDs disappear independently, closing2798ms. No assertions or contiguous-source protections were weakened; PR #227 remains Draft.

Next reproduce native forming-bar provenance and query missing_ranges using the actual cache/aggregator publication path. Determine whether an unconfirmed forming interval or a real confirmed-source gap blocks input, and verify recovery ownership separately. Do not bypass a genuine closed-prefix gap or repeat unchanged public attempts.

All33 original worktrees,3044 dirty files and original refs/statuses are unchanged. Current packages/profiles, failed Native evidence and rollback inputs remain protected. CI stays in the background; main merging requires a fresh exact-head/current-base applicable-check audit. [`receipt.json`](receipt.json) indexes exact commands and SHA-256-verified compressed raw evidence.
