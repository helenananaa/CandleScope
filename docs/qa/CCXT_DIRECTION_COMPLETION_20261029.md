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
  They share one egress group and one CDN bucket. Additional task-owned proxy
  instances using stored node configurations could not establish working TLS
  tunnels. Temporary instances and current subscription refreshes are being
  tested. The user's TUN and saved v2rayN settings are not changed.
  Independent-exit qualification remains open until distinct exits pass downloads.

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

- Real independent exits, asymmetric route speed/quota and sustained mixed
  archive/REST/WS load with a frozen cold-network/first-paint latency budget.
- Additional OKX archive products and historical periods beyond the qualified
  spot day; its archive feature remains explicitly opt-in and probe-gated.
- Additional production archive sources and third-party provider live/session
  qualification. Existing Bybit/Twelve Data/Kraken examples distinguish recorded
  or deterministic fixtures from live production support.
- Complete generalized recovery/strict-book policy work and adjacent data
  governance issues #112/#132/#135 are not silently closed by provider unification.

The PR remains a draft while these qualification limits are assessed. Code,
release assets, measured behavior and unverified requirements are tracked
separately; test counts are not summed across overlapping suites.

Machine-readable receipts are in [ccxt-integration-20261029](ccxt-integration-20261029):
the controlled comparison, both venue live summaries, public ZIP accounting,
OKX archive/REST parity and Windows packaged application/replay receipts.
