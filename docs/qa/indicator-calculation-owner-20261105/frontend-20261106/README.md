# Chart domain frontend and renderer qualification

Source `5458d54d92aaac8f0aa1484bafbdf92b2d0c7c2f` on main261 (`0de39f37`). This is the live hosted Pine
binding, with language-neutral calculation DTO/session handles/cache ownership.
Standalone history, provided-BAR/replay and builtin sharing keep their contracts.
The exact source file fingerprints, environment/commands and final minified
assets are in source-manifest.json; commands ran on the same file bytes before
this source commit. No SDK, bridge, wheel or installed Native package changed.

The hook opens one calculation, sends its reference to the private WS writer,
and routes HTTP projections through the existing bounded scheduler rather than
independent historical batching. Definition/context/left-origin changes and
unmount retire the old domain, including late opens. The handle retains only
metadata/bounded work handles. Complete HTTP reads and WS attachment carry the
full current projection; read-only ranges still do not execute the script.

Admission checks domain and nondecreasing generation/sequence before cache,
lines or auxiliary output mutation. A generation replacement must be a complete
snapshot and clears old cache coverage/provisional preview. Chart-owned cache
scope prevents opaque script projections from hydrating another chart, while
builtins remain shareable. Domain identifies the wire group; changing cursor
sequence does not resubscribe. Source-guarded closedThrough replaces the coarse
transport clock's older amendment frontier for this projection. Explicit forming
source finality is not promoted to closed solely by elapsed wall-clock time.

Single combined backend regression: **414 passed / 5 existing warnings / zero
skips**, including complete-vs-clipped read/no-IPC and strict complete flag.
22 real Manager/cache/SQLite/HTTP/WS cases show23 owned transport workers exit0
and independently absent, and all leases/callbacks/registries/source watches zero.
Related frontend regression: **375 passed / zero skips**; TypeScript, targeted
ESLint with zero warnings, and architecture checks pass. Previous413/378/268
records keep their own source identity and are not summed into this result.

The final Chromium run uses production-minified real React useIndicatorRuntime,
SingleChartPanes, HTTP/WS ASGI, real DataManager/cache/SQLite and repository
SDK/sidecar with qualified Pine core0.3.3+cs.1. Only BAR/feed production is
controlled. Counters:500,501,502,503; negative-offset point/marker/bgcolor delete;
second chart500 while first503; amendment rebuild gives first501 and second500,
matching each owner's observed prefix. Replacing the first chart's real input
parameter opens another domain500; a held genuine prior-domain HTTP response
cannot overwrite it or the second chart. Browser exit0/no remaining workers;
owned backend worker exit0/independently absent, all source resources zero after
full test-backend shutdown. Raw response/WS identities and shutdown are retained.

Earlier fixture rounds are preserved with explicit limits: the first used the
wrong chart series prop and an invalid named Pine parameter; second still used
that invalid parameter (PINE_INVALID_PARAMS), third proves the single-chart
pipeline; fourth exposed stale explicit-forming-vs-wallclock inference while
adding the second chart; fifth incorrectly expected the second chart to acquire
a forming observation it had never seen. The final fixture respects each
owner's prefix. These are not all product regressions: invalid parameter/prop
and second-owner expected count were fixture errors. The coarse closed frontier
and chart cache ownership were fixed from source audit and guarded assertions.

Original39 dirty QA fingerprints remain unchanged and excluded from commits.
**This does not qualify a Native installed package, macOS save/full-owned-quit/
restart, public exchange or Windows.** Original b784fb52/main250 Native500-to202
failure remains separate. Next: build/install exact source and required plugin
artifacts in an owned profile, rerun the original Native counter/parity/deletion/
marker/bgcolor assertions and save/full quit/restart before considering #227 ready.
