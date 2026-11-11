# Chart source wait and live recovery

Product source `02c9ea7a57a06a8a88ad42be39ec7ba702596057`, based on PR #227 head `81935f32bf25b9ef7506407c17723c5290f3ae6b`. Only production change is `backend/app/api/v1/chart_calculation_stream.py`; the inherited application host epoch fix remains intact. No frontend application/SDK/core/ASAR change.

## Defect and bounded recovery

A forming bucket can arrive before its predecessor is durably confirmed. The real source query correctly reports an untrusted/gapped closed prefix. Previously the chart writer treated this temporary `IndicatorRangeNotReadyError` as a fatal subscription failure and unsubscribed itself. Later real close events could not wake it, while the browser still retained its accepted subscription.

The actual aggregator bridge, cache, SQLite, event bus, ASGI HTTP/WS and SDK/core counterexample first proves six forming observations with the real empty preview provenance. It then advances the clock/bucket without finalizing the predecessor, reproduces exactly `Chart calculation input is not contiguous`, and proves no runtime execution through the gap. Before the fix an automatic recovery assertion times out after the real close; only explicit HTTP recovery/reattachment could resume it.

Keep the existing writer and its source lease on this specific source-not-ready error. Fence the calculation once per waiting period, report recovery-required once, and await subsequent source events. A successful retry must still verify the complete prefix and rebuild a new generation at the original origin. There is no polling timer, fabricated close, gap bypass or automatic acceptance of unconfirmed history. Other errors/delivery loss retain existing disposal behavior. Explicit close while waiting drains all resources.

The regression now receives a full-origin generation replacement directly from the same writer after the real durable close, then continues next-bucket observations without an HTTP recovery read or resubscribe. Durable revision adoption may evict an ephemeral preview; the test republishes it through the bridge, never by direct cache staging. Original full-origin, source-race, delivery-gap and cancellation cases remain covered.

## Evidence

Fresh single76-suite backend run: **980 passed, one Windows CRT-only skip, five existing warnings, zero failures/errors**. Focused three-suite run:26 passed. The26 ASGI/Manager/SQLite cases own27 SDK/core workers: all exit0 and independently absent afterward; callback/lease/registry/watch receipts are zero. Initial fixture recovery failure is retained: after durable adoption the next ephemeral preview needed genuine republication; it is not misreported as another product regression.

The previous failed Native profile was inspected read-only. Its preceding minute is first durably persisted about13.6s after the recorded source rejection, supporting delayed-close diagnosis. This is post-exit timing evidence, not the original missing_ranges payload. The actual aggregator counterexample independently establishes the failure/recovery mechanism.

## Actual macOS acceptance

A physical clone of the verified036 runtime overlays/compiles only chart_calculation_stream.py and receives a fresh strict signature. All1072 source/SDK fingerprints,164 built assets,9 plugin assets,76 plugin-source files and inherited full ASAR match before/after. This is a reused-runtime local candidate, not a release rebuild.

**The original full Native acceptance passes** with actual public BTCUSDT1m inputs: six distinct counter observations and both parities of negative-offset plot/toggle/marker/background updates, canonical closed rows, saved source, complete exit, same-profile restart and the same output adoption assertions again. Source text persists exactly. Both sidecars return0/signalnull, no kill requests; closes2383/2414ms. All20 app-owned PID entries are independently absent. The broader runner also observed36 descendant PIDs, including verification helpers; these are not relabelled as36 app processes. No renderer errors.

Both original Native sessions complete within one minute bucket. Therefore this run qualifies the original output/persistence/exit scope; it does **not** directly exercise minute-boundary gap recovery on a public feed. That path has the new failing-before/passing-after actual aggregator/SDK regression. No full issue152/O(N), Windows, fresh release or current-CI qualification claim. PR #227 remains Draft pending its remaining broader review/qualification.

## Storage and delivery

A separate reproducible-only cleanup deletes19 completed pytest/private-Chromium fixture directories. Observed free-space delta536039424bytes (about511MiB);12853 protected file hashes match, current Native app strict signature passes, all raw Native evidence/profiles/apps and rollback inputs are retained. No Native UI restart was claimed for cleanup itself. Completed test scratch can be regenerated from the exact retained commands; committed evidence is hashed and compressed in receipt.json.

CI continues in the background. A main merge still requires a fresh exact-head/current-base applicable-check audit. Continue native boundary/recovery qualification and the independent PR queue without waiting on development CI.
