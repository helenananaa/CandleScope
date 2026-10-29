# Public market admission

Implementation base: `b84b5e3d514e43fca556613fe107e29d12f7a329`, CCXT `4.5.60`.
This implements the shared admission layer discussed in #125. Business queues
continue to own series ordering, merging, repair progress and cancellation.
It does not replace them with a single FIFO.

## Product policy

- Foreground work waiting for quota does not globally stop background work on
  independent resources. Runnable foreground work still has execution priority.
- Waiting foreground/recovery demands protect the **same** quota from lower
  priority work. Necessary market metadata inherits the live caller's importance.
  WS startup metadata has recovery priority. Ordinary catalog refresh is
  background work, including the inline fallback when the catalog worker is
  unavailable.
- Background work may borrow idle capacity. After eight competing grants, an
  executable waiting demand receives one turn by original enqueue order, then
  the fairness cycle restarts. An old background cohort cannot burst ahead of
  all foreground requests together. The business dispatch queue uses the same
  eight-dispatch cycle, retains one background slot and preserves series order.
  Waiting age survives business deferral/retry. This provides finite progress,
  not a wall-clock promise while a source is unavailable. Transmitted work is
  not preempted or refunded.
- A request retains its exchange, product, symbol and data semantics. Only a
  compatible exit can change. Healthy WS connections are not rebalanced.

## Ownership and interfaces

`app/exchanges/public_admission.py` coordinates physical permits using the
existing `RateLimitManager`. `acquire_many_nowait` checks all distinct quota
constraints under the same admission lock, then debits them together. Duplicate
constraints on one bucket use the highest cost, not two charges for one attempt.
An impossible cost is rejected rather than silently truncated.

`PublicDemand` carries traffic class, owner, purpose, optional monotonic deadline,
defer behavior and optional business liveness. Shared metadata retains bounded
dependency interests and inherits their live priorities. Backfill returns a
`RateLimitDeferred` to its delayed heap instead of holding a worker while its
shared metadata task waits. Canceled/stale requests lose their quota protection.

`PublicPermit` has an attempt ID, reservations and idempotent response settlement.
Headers-only feedback retains the permit until completion. Unknown/canceled
attempts release concurrency but do not refund consumed quota. Reservation owner
identity allows a catalog IPC callback to settle the original probe while an
unrelated stale response cannot release it.

Quota feedback, permit completion, dependency promotion and demand removal wake
waiters. Refill deadlines remain timers. The physical wait queue is bounded at
1024 entries; the execution limit is 32 plus each rule's tighter concurrency.
These are local defensive bounds, not measured optimal throughput settings.
When execution slots are scarce, a lower-priority waiter yields the next slot
to a higher-priority waiter that can actually pass its quota/concurrency checks.
A higher-priority waiter blocked by an independent quota does not reserve that
global execution slot.

The budget owner is one backend event loop **including its managed catalog
worker**. The child sends admission/response messages over its existing pipes;
it does not create independent public quota. Cancel, worker exit and shutdown
release parent execution permits conservatively. Market parsing stays in the
child. Multiple independent backend processes or other programs are not covered.

## Physical paths

| Path | Integration | Coverage boundary |
| --- | --- | --- |
| Native REST/failover and historical fetcher | Common permits, existing endpoint rules and exact response feedback | Existing declared rules; other endpoints use the existing conservative fallback |
| Native catalog HTTP | Same owner and permits; background by default | Existing endpoint contracts |
| Default CCXT REST and strict Binance/OKX profiles | Hook `fetch`, once per physical HTTP attempt, including `fetch2` retries; task-local `on_rest_response` | Known Binance/OKX endpoints reuse native rules; other endpoint costs/windows remain partial |
| CCXT market bootstrap | Existing rail cache/singleflight; loader exit is charged; live dependency priority inheritance | Catalog worker and in-process runtime do not share parsed market tables across process boundaries |
| Catalog worker | Parent-owned IPC permits; complete network configuration preserved | One managed child; no distributed quota service |
| Archive resolver, probe, checksum and ZIP | Same public demand/permit, atomic route resource reservation and CDN quota; idempotent completion | Host/exit CDN buckets are independent of exchange API weight; physical HTTP ceilings span worker loops |
| Native WS | Gate before each `websockets.connect`; wrap application control sends | Automatic native pong frames run below the wrapper; one frame/s is reserved conservatively |
| CCXT WS | Gate each physical client `open` before its network timeout; wrap physical send/ping/pong | Pinned aiohttp client contract in CCXT 4.5.60; unqualified venue protocol rules remain partial |

CCXT's own throttler remains enabled. Logical CCXT history calls no longer
pre-debit one estimated request: metadata, multiple subrequests and retries each
receive a host permit at the physical boundary. Concurrent response accounting
does not read global `last_response_headers`. HTTP redirects performed inside
aiohttp and failures before a complete CCXT response body are not claimed to have
complete per-hop/header observation.

Balanced REST selection now includes local remaining capacity relative to the
request's cost and refill rate, alongside latency, active load and health. Explicit
failover ordering is preserved. Same `egress_group` shares quota; account/key
buckets are not multiplied by exits. Exit independence is configuration-declared,
not verified from actual public IPs.

## WebSocket rules and lifecycle

Rules checked against primary sources on 2026-10-29:

- [Binance Spot WS documentation](https://github.com/binance/binance-spot-api-docs/blob/master/web-socket-streams.md):
  300 connection attempts/5 min/IP; 5 incoming frames/s/socket including ping,
  pong and JSON control. The host applies the connection rolling window plus
  conservative 1.05 s pacing. Native application sends use 4 frames/s to leave
  protocol headroom. Native Binance client-generated pings are disabled; the
  library still answers server pings. CCXT explicit frames share the full
  five-frame window.
- [OKX WS documentation](https://www.okx.com/docs-v5/en/#overview-websocket):
  3 connection requests/s/IP and 480 subscribe/unsubscribe/login requests/hour
  per connection. The host uses these rolling windows plus 0.5 s connection
  pacing and 0.11 s control pacing. Heartbeats do not spend the hourly control
  allowance.
- Binance derivatives and other generic exchanges currently use conservative
  local connection/control pacing; these are **not** complete vendor qualification.

Logical descriptor leases and healthy connection affinity are unchanged. Shared
runtime reuse does not charge another connect; every actual reconnect does.
Reconnect supervision uses bounded exponential backoff with jitter. Quota errors
do not increment proxy network-failure counters or force route migration.
Closing a client cancels queued connection attempts and unsent control messages;
closed-socket control buckets are retired. Protocol heartbeats have higher
admission priority than queued subscriptions.
The last runtime subscriber also cancels a pending market bootstrap; one
subscriber leaving does not cancel a bootstrap still needed by another.

## Diagnostics and rollback

Transport diagnostics include `public_admission`: owner scope, coverage label,
pending/protected/in-flight counts, oldest wait, traffic-class counts, deferral
reasons, deadline misses and the last 128 settled attempts with bucket costs and
elapsed time. Existing limiter/proxy diagnostics retain token estimates, cooldown,
probe state and route health. No credentials or proxy URLs enter attempt history.
The API does not yet supply user-facing deadlines for every business operation;
deadline statistics only cover callers that actually provide one.

`get_public_admission().set_priority_enabled(False)` disables the added priority
protection while preserving consumed tokens, cooldowns and active permits. It
does not bypass physical admission. Re-enabling uses the same ledger. There is no
claim of a completed multi-stage shadow/production rollout or independent
metadata/WS feature-flag UI in this change.

## Archive integration (#124)

The production archive downloader now acquires a `PublicPermit` with its bound
route as an atomic resource reservation. It holds no route while waiting for
quota. The shared public execution limit also includes archive attempts.
Process-owned HTTP resources enforce global/host/exit ceilings across loops and
reserve the last route slot for REST. CDN 418/429 cooldowns cover the same host
and exit across aliases and venues, without cooling unrelated hosts or REST.
The declared conservative fallback is eight requests/second per host/exit; this
is a local safety policy, not a claim about the vendor's published limit.

Deferred business chunks return to their scheduler without negative caching,
disabling the source, or falling back to REST as if a download failed. Completion
releases resources exactly once; canceled/unknown attempts do not refund quota.
Quota and demand ownership still belong to the backend event loop; process-wide
archive resource limits do not imply a distributed quota service. Storage,
import proof, deletion and persistence contracts are unchanged.

Failed non-blocking inspections and unchanged protection registrations do not
broadcast resource changes. Probe completion wakes waiters; its deadline is a
fail-safe expiry. Archive configuration is rechecked at most four times per
second in the absence of notifications. A held-probe regression prevents peers
from waking each other in a retry loop. Current integrated and live evidence is
recorded in [the PR #145 completion report](qa/CCXT_DIRECTION_COMPLETION_20261029.md).

## Validation scope

The added tests exercise atomic constraints, independent resources, critical
protection, cancellation, probe ownership across IPC, rolling windows, priority
rollback, metadata inheritance, control cancellation, capacity-aware route choice,
and real loopback HTTP/WS through production CCXT clients. Existing backfill,
catalog, cache/singleflight, proxy/WS lease and provider tests remain required.

Verified on macOS/Python 3.12.15 with pinned CCXT 4.5.60, 2026-10-29:
**335 passed, 13 deprecation warnings, 63.10 seconds**. Warnings came from
aiohttp connector cleanup, Starlette's blocking portal alias and FastAPI
`on_event`. The run used an isolated `DATA_DIR`; no exchange credentials or
public exchange traffic were used by the added integration scenarios.

Specific physical-path evidence includes:

- Default production CCXT history transport: one metadata download reused across
  two history calls; one host permit per physical request, with the bound exit.
- A CCXT `fetch2` internal retry after HTTP 503: two network attempts, two
  separately settled permits, statuses 503 then 200.
- A real catalog child: parent-owned quota and probe settlement; canceling an
  active child request releases parent concurrency with unknown-outcome feedback.
- A real CCXT WS client: repeated logical connect reuses one socket; subscription
  and initial protocol ping are counted separately. Closing during a 60-second
  quota cooldown opens no socket, cancels pending futures and prevents late sends.
- Shared metadata: a deferred foreground caller promotes an existing background
  load; cancellation removes its priority; the load still runs only once.
- Saturated execution slots: runnable foreground takes the next released slot;
  quota-blocked foreground permits independent background work to proceed.

Reproduce from `backend/` after installing the pinned runtime and test
requirements (plus `pytest-timeout`). Warming imports before the per-test timeout
keeps cold CCXT/pandas import time separate from scenario execution:

```sh
DATA_DIR=/tmp/candlescope-125-tests PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -u - <<'PY'
import pandas, exchange_calendars
from app.exchanges.registry import bootstrap_default_adapters
bootstrap_default_adapters()
import pytest
files = """
test_public_admission.py test_public_transport_loopback.py
test_backfill_rate_limit.py test_transport_http_rate_limit_metadata.py
test_ccxt_shared_markets.py test_ccxt_provider_runtime.py
test_backfill_coordinator.py test_proxy_pool.py test_proxy_pool_ws.py
test_proxy_pool_traffic.py test_ccxt_unified_provider.py
test_ccxt_binance_usdm_extension.py test_catalog_worker.py
test_symbol_catalog_refresh.py test_multi_chart_upstream_shards.py
test_ingestion_session_types.py test_native_session_transport.py
test_stream_transport_close.py test_transport_ws_urls.py
test_ccxt_owned_close.py test_ccxt_binance_spot_extension.py
""".split()
raise SystemExit(pytest.main(["-q", "--timeout=90", *[f"tests/{f}" for f in files]]))
PY
```

Loopback results establish controlled physical accounting and lifecycle behavior.
They do not establish real exchange throughput limits, public exit independence,
native GUI latency, cold-network P95, or complete multi-venue WS qualification.
Those acceptance stages remain open under #125/#107; no acceleration percentage
or production readiness claim is inferred from unit-test counts.
