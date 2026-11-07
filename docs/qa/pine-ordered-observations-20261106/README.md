# Ordered Pine observations and source-fenced recovery

Current product source `9b67ff5a872e532f699e76e88b5af4b9746525b5`, ordered-input implementation `bba23c728ee28269f71e2a717420acbb1df6e5fb`, based on PR #227 head428e03a1/main7ac. Only four backend production files change; frontend application, SDK/core, ASAR and published wheels stay unchanged. **PR #227 remains Draft; latest full Native qualification is not established.**

## Confirmed input loss and bounded ownership

A deterministic scheduling barrier pauses the first real SDK/core execute. Six distinct forming DataEvents then produce only two executions on428. The actual event bus also merges pending previews for ordinary display consumers. Such merging does not preserve Pine varip execution semantics (#152).

Chart Pine subscriptions now opt into preserving updates through the existing DataManager/event-bus owner. The single existing chart writer retains at most64 pending input observations in order. Its storage query still proves the confirmed prefix, while an admitted forming event supplies its own immutable prices rather than rereading a later live-cache value. Neither a new history cache nor another mathematical owner is introduced. Distinct same-bar events remain distinct; downstream display coalescing is separate. Other consumers keep their established preview policy.

When either the event-bus queue or chart input budget fills, admission terminates with an explicit recovery notice; final-only journal replay cannot pretend to restore discarded previews. A real-bus regression found that unsubscribing cancelled its calling recovery task before its terminal notice was queued. The notice is now published before owned disposal. Explicit shutdown still drains/relinquishes resources.

The actual SDK regression now executes six observations and verifies counter501..506 plus distinct even-price old-time outputs102/104/106 and odd deletions. Source correction during live execution is separately reproduced on an isolated Git archive of428. The writer formerly disposed itself with SOURCE_CHANGED; it now fences the in-flight result, retains source ownership and rebuilds from the original origin. One queued recovery wakeup is retained without its stale preview. This is not precise intrabar replay across a source repair.

## Canonical close guard

Review of the new event-input path found a distinct interleaving before delivery: a queued close contains102, a newer authoritative SQLite correction contains104, and the actual query proves104. The initial implementation could execute102 while acknowledging the newer confirmed prefix. A cold actual ASGI/SQLite/SDK counterexample reproduces that precise wrong-price publication onbba.

The final9b67 guard compares queued closed OHLCV with the canonical queried close before runtime execution, then uses canonical rows. A mismatch is fenced and recovery uses104 in a new full-origin generation; there is no invalid runtime call or falsely acknowledged old price. Only forming observations may substitute their captured intrabar values, and they cannot unconfirm an already admitted closed frontier. The initial attempted barrier happened too early and the existing source proof correctly rejected it; that harness/interleaving result is retained separately from the successful counterexample.

## Local evidence

Final9b67 single83-suite invocation: **1097 passed, one Windows CRT-only skip, five existing warnings, zero failures/errors**. Four focused suites:41 passed. The30 actual ASGI/Manager/SQLite cases own31 SDK/core workers; all return0 and are independently absent, with callback/lease/registry/watch receipts zero. The earlierbba run reports1096, separately, without combining the two counts. The first isolated-baseline setup lacked backend/scripts and failed before tests; the corrected Git archive executes the source-race counterexample. Original logs/commands are retained.

## Native evidence and remaining failure

The previous02 source passed the original shorter output/save/full-exit/restart scope. A new driver adds the next wall-clock minute source bucket to each adoption phase, keeps all original output/monotonic/source/persistence assertions and the original120s phase deadline, and uses a fresh profile. Read-only execution links do not modify the retained app. On02, the first boundary phase passes; the restarted phase receives SOURCE_CHANGED, loses its writer and times out. Both sidecars exit0 without kill requests.

The new physicalbba candidate clones verified02 resources, overlays/compiles the four backend files, and receives a strict signature. All1072 source/SDK fingerprints,164 built assets,9 plugin assets,76 plugin-source files and inherited ASAR verify before/after. This is a reused-runtime candidate, not a frontend/release rebuild.

**The unchanged strengthened Native driver still fails onbba.** A public-feed source fence is followed164ms later by an adopted full-origin snapshot on the same live client (generation3, sequence5): automatic recovery is now observed. Its varip counter changes1502→1501, so the original monotonic-counter assertion fails. The next-minute bucket requirement and subsequent save/restart are not reached in this run. Do not relabel this as complete Native success, precise intrabar restoration, or a new UI result for9b67. Thebba sidecar exits0/signalnull/no kill; all10 app-owned PIDs independently disappear, close3066ms. All failure observations/profiles remain retained.

A full-origin rebuild from final OHLCV cannot establish the old opaque intrabar path. Preserve the failure and audit the pinned public checkpoint/replay capability and explicit reset/qualification reporting. Do not bypass source correctness or silently weaken the original monotonic assertion to manufacture acceptance. Full #152 protocol, fault matrix and O(N) performance qualification remain open, as do Windows and release qualification. No repeated unchanged public attempt is scheduled.

## Queue and storage

Live inventory:18 open PRs and46 open issues. #233 and #200 are merged. #204 is closed/unmerged; #249 remains in the independent alert queue. #147 is closed/unmerged and its head is an ancestor of actual main7ac; this does not close full #131. #75 is closed/unmerged and its performance candidate remains unadmitted. Preserve those original scope decisions. Continue #223/#218 native qualification and the strategy stack while larger Pine recovery contracts are assessed; development does not wait for CI. A main merge requires a fresh exact-head/current-base applicable-check audit.

The Windows connector again returns gateway429 before any host command, not a Windows test result. A separate cleanup removes11 completed scratch/Git-archive roots, freeing an observed765116416bytes (about730MiB). All6365 protected file hashes match; two retained apps pass strict signatures. Current Native profiles/apps/raw evidence, previous passed package, rollback inputs, user work and the active latest test run are protected. No Native UI restart was claimed for cleanup. Commands and compressed SHA-256-indexed evidence are in receipt.json.
