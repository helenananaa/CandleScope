# Current R129/D126 macOS native reconstruction receipt

Tested product: `9fbbe3d89c295536d03b17cabec4875941163b3a`, containing PR #373
and the PR #374 target-lifecycle patch. Date: 2026-11-12. Refs #126 / #129.
Parent issues remain open.

## Result

An isolated macOS arm64 packaged application passed a complete native workflow
against real public OKX BTC-USDT spot history/realtime. The profile started empty:
no market seed, fake storage, local market replay or substituted response.

| Stage | 45m closed rows checked | 90m closed rows checked |
| --- | ---: | ---: |
| Initial open + explicit deep-history pagination | 628 | 533 |
| Switch to 1m/5m, then recreate derived targets | 628 | 533 |
| Save, full process exit, restart same profile | 628 | 628 |

All **3,578** comparisons checked open/high/low/close/volume/quote_volume/trades/
taker_buy_base/taker_buy_quote against strict canonical reads; saved anchors were
also compared through reconstruction and restart. Workspace persistence reported
`saved` at every checked stage. Both owned process trees exited completely
(10 processes / 6,668 ms, then 9 / 1,715 ms); the harness did not terminate other
installed applications. The derived-target release phase reported zero history
prefix targets/tasks/seeding; those small targets did not adopt compact prefixes.

The application was launched twice from the packaged executable and bundled
backend/runtime. Deep strict code-signature verification passed before and after
execution, and all **999 tracked backend app files** still matched the tested
source hashes after execution. UI screenshots and full bounded receipts are in
`evidence/`, with SHA-256 index and a compact native summary.

## Package provenance / reproduction

The standalone base package was built from
`ef8f0e0fa6df299a823f4460b701eb1c3c98361f` by the normal build path, then cloned
into this task's own ignored desktop-dist directory. All tracked backend app
files were overlaid from the tested product, stale copied Python bytecode was
removed from that clone, and the clone was sealed again with an ad-hoc signature.
There are no frontend/packages source changes between that build revision and
the tested product. Frontend, dependency runtime and first-party plugins retain
the verified base package; this receipt does not claim a new clean frontend or
dependency build. No user's installed app or primary design checkout was edited.

The existing [native driver](../aggregation-closeout-20261112/native.mjs) was used
unchanged with Playwright Core 1.56.1 in an isolated output tooling directory:

```sh
CANDLESCOPE_PLAYWRIGHT_PACKAGE="$PWD/output/r129-native-current-20261112/tooling/package.json" \
CANDLESCOPE_AGGREGATION_NATIVE_OUTPUT="$PWD/output/r129-native-current-20261112/native-cold1" \
CANDLESCOPE_AGGREGATION_DEEP_HISTORY=true \
node docs/qa/aggregation-closeout-20261112/native.mjs
codesign --verify --deep --strict frontend/desktop-dist/mac-arm64/CandleScope.app
```

The source manifest records actual app.asar/backend hashes and assembly scope.
Original profiles, market databases and unredacted control context remain privately
under output. Published receipts redact only ephemeral action contextToken values;
they do not remove failures or replace data. This native run had no failed attempt.

## Acceptance boundary

This qualifies this backend revision's two-chart cold loading, explicit left
pagination, target release/recreation, canonical field parity, native save and
full-exit/restart on macOS arm64. It does not qualify Windows/Intel, all providers,
native amendment/delete injection, long-bucket compact-prefix reconstruction,
indicator/strategy input equivalence, hidden recovery, soak/performance budgets or
whole-runtime RSS. The settings diagnostics endpoint does not expose shared-input
counters, so this run is not a direct native sharing-hit/per-owner heap proof;
component/work-cost evidence remains in the PR #373/#374 reports.
