# PR #145 implementation and qualification update

This continues the single [PR #145](https://github.com/helenananaa/CandleScope/pull/145).
It supersedes the pending-work assessment in the earlier integration record;
the earlier measurements and failed attempts remain historical evidence.

## Implemented

1. One registry-owned CCXT provider, thin venue bindings and finite protocol
   strategies. Dataset vendor/venue identities and custom-provider contracts are
   preserved. Full generic rows are retained without inventing capabilities.
2. Both the business backfill dispatcher and public physical admission guarantee
   an executable aged demand a turn after eight competing grants. Only one aged
   turn is granted per cycle; foreground preference resumes afterwards.
3. Archive requests use the same public demand/permit scheduler with atomic
   route reservations. CDN host/exit quotas remain distinct from exchange API
   weights. Waiting owns no route; admission deferral does not negative-cache
   an object, disable its source or bypass admission through REST fallback.
4. Slow real downloads exposed peer-wakeup churn. Repeated failed inspections
   and unchanged protection registrations no longer broadcast resource changes.
   Probe completion wakes waiters; expiry is a fail-safe timer. Archive config
   changes are rechecked at most four times per second when no event arrives.
5. The pinned CCXT fork is published, installed by default and verified before
   desktop runtime promotion. Pine calendar and existing Renko contracts are
   combined, versioned, qualified and published for four native platforms.

See [provider ownership and rollback](../ccxt-provider.md) and
[public admission](../public-market-admission.md). Budget ownership remains one
backend event loop with coordinated catalog workers. Process-wide archive
resource ceilings do not establish global multi-backend quota coordination.

## Release evidence

| Asset | Evidence |
| --- | --- |
| CCXT fork `candlescope-4.5.60.1` | Source `43f7d748b22757873e1b81776e150ca67b67da07`; wheel SHA-256 `8520ad4b0f9004f6340da3da49ec7f455fc7579d85cb375d145741f3806f625c`; published wheel downloaded, installed and verified |
| Pine bridge `0.3.3`, engine `0.3.2+cs.1` | Upstream `28ecae3c645e9269e2099d27cc9abbb1f52ee9ea` plus `host-contracts-v1.patch`; four source-build jobs each passed 87 tests, no skips, on `59f64ce6fcc31ff85ce64ca284ffaf79cf019eed` |
| Published Pine bundles | Windows AMD64, Linux x86_64, macOS arm64/x86_64 each re-downloaded release assets, checked manifest/wheel hashes, reproduced the exact bundle digest, installed offline and passed installed host tests |

Source-build [run 40835252471](https://github.com/helenananaa/CandleScope/actions/runs/40835252471)
and published-assets [run 40836998177](https://github.com/helenananaa/CandleScope/actions/runs/40836998177)
are successful. Native host tests cover DST `time_close`, same/cross-timeframe
requests, strategy results, replay seek/snapshot/play, process reopen and history
repair. This is not certification of every Pine language feature.

## Current acceptance evidence

- Final backend integration including the slow-network wake fix: **600 passed**,
  no skips, in 166.52s. One aiohttp deprecation remained. The final archive wait
  interval also passed **41 targeted tests**. Counts overlap and are not summed.
- Node 24 frontend checks: **4443 passed, 1 platform skip**, including the isolated
  drawing command performance gate. The functional suite took 114.9s locally.
- Windows packaged app: bundled Python and fork verification, three real pages,
  two launches and graceful exits passed. Packaged replay creation, stale-draft
  recovery after deletion, step/reload, hub reopen, full app restart and 4h
  switching passed with synthetic history and a matching persisted catalog.
- The first replay attempts lacked instrument metadata because live Binance
  spot catalog loading failed. The corrected offline smoke seeds the catalog
  through the normal snapshot reader. A duplicate button label was resolved with
  its observed action attribute. No product admission check was bypassed.
- Current desktop host tests: **123 passed**. The Windows Vite/package build
  passed; large-chunk warnings remain. macOS full app packaging CI is tracked
  separately from the successful four-platform Pine release gates.
- Actual default-provider/fork network runs: Binance spot and USD-M, OKX spot
  and swap all passed REST → forming/closed WS → REST reconciliation → durable
  source evidence → process readback, with zero pending deliveries. OKX required
  the existing local proxy because direct DNS resolution failed. Its supported
  trade/ticker/depth/mark/index/funding REST/WS paths passed; open-interest WS is
  explicitly unsupported. Earlier attempts are retained, not relabelled passed.
- Public Binance Vision download: January–April 2024 BTCUSDT daily candles,
  four monthly ZIPs, **121 rows**, official SHA-256 validation and warm-cache
  reread passed through the default registry and production permit/cache path.
  Eight physical requests settled once, with no active lease or permit left.
  This small-file check does not measure bulk import throughput.
- Live OKX archive probe succeeded. The 2026-10-24 BTC-USDT spot daily ZIP
  contained **1440 rows**; five default-provider REST pages returned the same
  timeline, OHLCV, quote volume, close boundaries and closed state, with **zero
  differences**. Warm reread retained the same digest. This uses local SHA-256
  and schema validation; OKX supplies no checksum sidecar. Archive enablement
  remains explicit and each runtime still probes the website contract.
- The two existing v2rayN listeners were measured to have the **same exit**.
  They share one egress group and one CDN bucket. Subsequent task-owned proxies
  using the authorized subscription, host DNS and physical-interface binding
  established **two distinct exits**. Neither TUN nor saved v2rayN settings was
  changed. Initial remote-DNS/transport failures remain recorded locally.
- Through those two exits, four 2024 monthly **1m** ZIPs downloaded and parsed
  **174240 rows / 8525230 ZIP bytes** in **15.812s**, with official checksums and
  warm-cache identity intact. Each route carried four archive requests; no
  failed archive attempt or active lease remained. During downloads, eight
  foreground REST calls succeeded (seven began with two archive leases active)
  and eight real WS frames arrived, maximum observed inter-frame gap 2.031s.
  REST durations were 562–2375ms, including the initial cold request. There is
  no inferred first-paint or percentile SLA from eight requests.
- The preceding small-file dual-exit run also completed all four objects;
  one failed physical attempt was settled as unknown and retried through the
  alternate route. Both the failed attempt and final successful objects remain
  in its receipt. The large mixed run had no archive failures.

## Controlled fairness comparison

`backend/scripts/qualify_public_admission.py` runs three pairs against an actual
loopback HTTP server: 128 foreground + 32 background requests, one execution
slot, 2ms declared handler delay. The strict-priority baseline first serves
background at position 128; bounded bypass serves it after eight foreground
grants. All six runs issued exactly 160 HTTP requests and produced the same
result digest, with no pending/in-flight work at exit.

| Observation | Strict priority | Bounded bypass |
| --- | --- | --- |
| First background position (zero-based) | 128 | 8 |
| Foreground wait P95 across 3 runs | 3927–4249 ms | 3635–3802 ms |
| Background wait P95 across 3 runs | 4182–4511 ms | 3780–3950 ms |
| Event-loop lag P99 | 45–51 ms | 43–47 ms |
| Total wall time | 4.20–4.54 s | 3.80–3.97 s |
| Python traced peak memory | 819–900 KB | 831–835 KB |

These are observations on this Windows host, with ordered baseline/candidate
runs and no statistical performance claim. They establish finite progress and
result parity, not public service speed, native first-paint P95 or a frozen SLA.
CPU, queue, request and latency details are in the machine-readable receipt.

## Remaining acceptance boundaries

- Sustained mixed archive/REST/WS load, a frozen cold-network/first-paint latency
  budget, and a controlled before/after full-import CPU/memory/disk comparison.
  Short public dual-exit success is not a production-load or speedup claim.
- Additional OKX archive products and historical periods beyond the qualified
  spot day; its archive feature remains explicitly opt-in and probe-gated.
- Additional production archive sources and third-party provider live/session
  qualification. Existing Bybit/Twelve Data/Kraken examples distinguish recorded
  or deterministic fixtures from live production support.
- Complete generalized recovery/strict-book policy work and adjacent data
  governance issues #112/#132/#135 are not silently closed by provider unification.

The integration is eligible for its scoped merge after the current-head CI
gates pass. The limitations above stay open in the linked issues; merging this
foundation does not complete the broader acceptance matrix. Code, release
assets, measured behavior and unverified requirements remain separate; test
counts are not summed across overlapping suites.

Machine-readable receipts are in [ccxt-integration-20261029](ccxt-integration-20261029):
the controlled comparison, both venue live summaries, public ZIP accounting,
OKX archive/REST parity and Windows packaged application/replay receipts.

## Backend PR alignment follow-up

The full #137 interval-admission history is now included, together with the
common #148 fixes for OKX notices, socket interruption, stale observations and
the last unclosed bar's repair range. The subscriber-specific strict/gap-aware
feature remains in #148. #138's durable revision work stays independent.

Requested unavailable intervals remain visible until the user explicitly
selects a qualified interval. Capability fixtures now declare their BarBasis;
an ordinary Binance USD-M source keeps its own identity and does not acquire
continuous-contract or second-bar qualification by implication.

Historical source-component recovery now uses a DataManager-injected reader.
The aggregator cannot import the storage backend directly. The CCXT integration
runner includes the architecture boundary regression to preserve this rule.

The branch incorporates main through `ce07e1bf` (independent #133/#134/#136/#140
and #110/#111), with these final local results:

- **680 passed, 0 skipped** in the pinned-fork CCXT/architecture integration
  run, 157.76s; one aiohttp deprecation. The earlier 620-test run is superseded.
- **170 passed** in the API/lifecycle/source-recovery/aggregator follow-up.
  It overlaps the integration run and is not added to its count.
- Full `npm run check`: **4529 frontend tests passed, one platform skip**,
  the separate performance test passed, and **123 desktop tests passed**;
  architecture, translations, type checks, lint and build passed.
- Chromium exercised all **six interval-admission scenarios** with no uncaught
  exception or remaining worker. Its controlled seconds fixture was then made
  type-correct; full TypeScript checks and its ESLint check passed again.

Logs are retained locally under `output/ccxt-integration`:
`owner-integration.log`/`.xml`, `owner-final.log`, `final-joint-frontend.log`,
`final-interval-admission-browser-v2.log`, `owner-typecheck.log` and
`owner-browser-lint.log`. The browser fixture uses controlled capabilities,
not live market or native-package evidence. Earlier native/public-network
receipts above retain their original scope and are not claimed as new runs.

After #145 merges, #138 and #148 return to a main base. #147 requires the common
provider and revision contracts; #144 additionally requires the public #130
block contract and removal or convergence of its private-cache experiment.
The Pine host stack #81/#128 must preserve the published runtime/lock contracts.
Those branches retain their own Draft and acceptance boundaries. No new PR is
needed for this integration.
