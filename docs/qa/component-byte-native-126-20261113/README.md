# Component accounting native observations — #126/#127/#129

macOS arm64 packaged application, isolated profiles, real public OKX BTC-USDT
spot, no seed database or response replacement. Each app is an APFS clone of the
existing native bundle: all 1000 tracked backend/app files are overlaid and the
bundle is sealed again. Frontend, runtime and plugins are unchanged from base
build `ef8f0e0fa6df299a823f4460b701eb1c3c98361f`. This is assembled-backend
qualification, not a clean frontend build, Windows or Intel qualification.

The existing local HTTP proxy at 127.0.0.1:7897 was supplied only to the isolated
app process. No system networking settings or default 8-second HTTP timeout were
changed. Source manifests, signature checks, process receipts and traffic are
retained. Only ephemeral control-context strings are redacted from archived
receipts; numeric active_read_tokens remain intact. Original profiles, SQLite
databases, apps and logs remain in the isolated worktree's output directory.

## Revision 5d93: original workflow passed

`5d93d3037901980b64983b13f9276a876cd293aa`, native-original5d.mjs:
empty profile → 45m/90m viewport → explicit deeper history → switch 1m/5m →
recreate → save → complete process exit → relaunch/restore. **3768 closed-bar
nine-field comparisons**, 628 per custom interval at each of three phases,
passed; workspace saved at checkpoints; both owned process trees fully exited;
no page errors. Packaged source/asar hashes and signatures match before/after.
The top-level screenshots and evidence directory describe this revision.

Actual initial source frames were observed. Stream counters at the immediate
recreate/restart checkpoints were zero, so sustained live updates after restart
were not established. The restored 90m screenshot shows a header/plot last-price
difference (73629.5 versus 72597.6); forming/header price is not asserted by the
closed-bar comparison and is not accepted here.

## Final revision 04667: stricter workflow failed

`04667fad927f20413add2475f12e42e94c3fc663` adds empty-proof byte accounting.
The extended driver requires actual source frames at every phase. Initial source
frames and 628 closed comparisons per custom interval passed, then the unchanged
500-row readiness gate timed out after switching to 1m/5m. Their views held
203/202 rows, marketReady=false, with 109 received frames each. This is **not a
complete final-revision native pass**. All owned processes exited; no page errors.
See final046 evidence, including the package provenance and failure receipt.

Read-only inspection found 300 unacknowledged selected source heads per native
interval while the canonical history was absent. The requested 1m bounded public
history page was separately available (300 rows, HTTP 200). Reconstruction of one
pending head per interval passed the existing numeric/current-source filter.
This narrows investigation to projection/acquisition lifecycle; it does not yet
prove causation or authorize weakening revision/deletion fences. The original
database is preserved. A further 5d93 diagnostic run with warning logging failed
earlier on catalog timeouts and cannot isolate the switch failure.

Driver imports the retained backend-batch1 driver/value probe and accepts
CANDLESCOPE_PLAYWRIGHT_PACKAGE, CANDLESCOPE_AGGREGATION_NATIVE_EXECUTABLE,
CANDLESCOPE_AGGREGATION_NATIVE_OUTPUT, CANDLESCOPE_AGGREGATION_PACKAGE_REVISION,
CANDLESCOPE_QA_HTTP_PROXY and CANDLESCOPE_AGGREGATION_REQUIRE_LIVE. Use a fresh
output/profile per run. native.mjs includes additional failure diagnostics;
native-original5d.mjs preserves the exact first successful workflow.
