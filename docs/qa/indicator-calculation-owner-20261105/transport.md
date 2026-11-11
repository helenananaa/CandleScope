# HTTP/WS chart-domain backend integration

Product/test source: `3b8a6dde0df6d9d4236c05ac7fce367d004745a3`, with initial
integration source `1a879714` and main200 `a1302842`. The explicit backend chart path is now wired;
**the existing frontend hook still uses independent history and is not yet
bound to this contract. The original Native counter failure is not fixed or
qualified by this step.**

[Chart calculation domains](../../architecture/CHART_CALCULATION_DOMAINS.md)
specifies versioned open/range/delete endpoints and script WS attachment.
Origins/definitions are fixed; read-only range views borrow the existing SDK
projection. HTTP catchup, real-time output and correction share the same owner.
The last admitted confirmed bar is a physical overlap anchor, not a finite
warmup replacement for cumulative state. New generations publish full snapshots;
normal live output retains the existing replace-range/deletion/scene contracts.
The domain has one writer, idle WS lifetime holds, bounded command/coalescing
queues, source revision/delivery fences and explicit close/disposal.

The single final backend combination is **268 passed / 5 existing warnings /
zero skips**. It includes the earlier owners/runtime/patch/history/lifecycle
coverage plus old WS resume/owner/correction fanout, range cache, data bridge,
host inputs and actual Pine requested-update/window strategy flows. Tests use
the retained copies-venv launcher and current repository SDK/Pine modules with
core **0.3.3+cs.1**. SDK/bridge package source bytes are unchanged from `1f9ada60`;
their earlier 185 and 240/one-skip suites retain that earlier identity and are
not re-counted as this run.

`test_chart_calculation_transports.py` runs thirteen actual FastAPI TestClient
HTTP/WS ASGI cases, registered runtime service and subprocess SDK/Pine IPC. The
authoritative BAR source and its event delivery are deterministic fixtures.
There is no real network exchange, renderer, installed-package or Native claim.
No provider math, runtime output or protocol reply is substituted. Assertions:

- HTTP initial counter **500**, same-owner WS **501 → 502 → 503**. Negative
  offset range covers the earlier changed time; odd updates delete the point,
  marker and bgcolor. A source amendment rebuilds **501** at generation 2 with
  a complete origin snapshot.
- Covering HTTP views and cold WS join do not add execution/IPC or seed another
  runtime. Independent chart B remains **50**. A narrow right catchup gives
  **501** from the confirmed overlap, not a separate 201-bar calculation.
- Stale HTTP references return the current position; malformed/future schema
  fields cannot execute. Changed definitions cannot attach. A duplicate writer
  is rejected with the specific writer-busy code and leaks no lifetime hold.
- HTTP cannot bypass an active parent-repair barrier. Closing during that wait
  cancels only the source waiter and completes before the parent; a successful
  parent completion rebuilds once, and duplicate completion adds no IPC.
- HTTP DELETE drains and detaches a quiet active WS, market leases and durable
  owner. Idle holds protect against TTL expiry but cannot block retirement.
- WS reconnect retains **501** without IPC/reseed; the next changed forming
  observation gives **502** in the same generation. Closed bars arriving in
  the HTTP-to-WS gap are caught before the initial snapshot.
- A stopped-worker output read does not launch one. Only explicit rebuild
  recovers at the origin and generation 2. A missing new input bar cannot
  execute an old prefix or advance the cursor as a successful catchup.
- A source change during actual execution cannot publish or notify the alert
  observer, and failed open cleans its orphan. Actual compiler errors retain
  the original diagnostic and line 3. A source delivery gap forces an origin
  rebuild/new generation even if the primary revision token did not change.

`transport-observations.json.gz` records counter/position/range observations,
query windows and process cleanup from those assertions. All **14 owned worker
processes** (including the explicit restart case) exit normally with code 0 and
their PIDs are independently absent. Each case ends with zero source callbacks,
market leases and registry entries. This proves component-process cleanup, not
desktop save/full-owned-quit/restart. The 39 pre-existing dirty QA files keep
their exact hashes and are neither staged nor overwritten.

The preserved forming failure found two actual integration constraints: a tail
containing only a forming bar omits the admitted confirmed frontier, and the
runtime needs a confirmed overlap anchor. The adapter now carries the admitted
frontier when absent from the supplied tail and queries that exact confirmed
anchor. It still refuses a source that actually unconfirms a supplied frontier
or an unexpected reset; no warmup is enlarged and no assertion is weakened.

The first wider run also caught a refactor error: the legacy correction closure
lost its returned shared fanout state. The common helper now returns that state
to the original closure, and the original parent-barrier/closed-race tests pass.
The failed log is retained. Additional installed-adapter tests first skipped
without explicit qualification flags; enabling flags alone selected an old
user registry. The final run uses the isolated registry and source module runner
recorded in `transport-test-environment.json`, with both test flags enabled and
zero skips. No dependencies were installed/upgraded in a retained interpreter or user
installation; the final source qualification uses its explicit isolated registry.

Evidence is scoped by `transport-source-manifest.json`, the three compressed
logs, environment record and case receipts. To rerun, use its listed backend
test files with the qualified launcher, isolated DATA_DIR/CANDLE_DATA_DIR,
explicit CANDLESCOPE_NATIVE_RUNTIME_REGISTRY and both NATIVE_TEST_PYTHON flags
pointing at a shell launcher of `source_runtime_runner.py`. The recorded small
source launcher/registry are regenerable; they are not installed-package proof.

Next: audit/qualify the real DataManager transaction-owned prefix boundary for
initial HTTP-to-WS acquisition, background writes and parent chunks. Coarse
transport revisions and controlled BAR fixtures do not by themselves prove that
source acquisition/commit boundary; bind the existing prefix facade where the
actual call chain requires it before enabling the chart hook. Then wire
frontend domain ownership, range scheduling and WS subscription,
accept generations/sequences atomically, dispose old domains on replacement,
then real service+renderer and final source-matched Native save/full-quit/restart
with the original monotonic/parity/deletion/marker/bgcolor assertions. Windows,
public-market qualification and whole #152 remain separate and open. CI stays
in the background until a main merge is proposed.
