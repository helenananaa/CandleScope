# Issue 117 qualification — 2026-10-29

Scope: independent `codex/issue-117-fixed-anchor` worktree, based on `b84b5e3`.
This continues the UTC OKX, bidirectional minute-anchor and native Pine anchor
commits `0c70504e`, `1fec0b0e`, `f3335c90`. No original user profile/database was
migrated. No Windows operation or desktop packaging acceptance was performed.

## Implementation

- Versioned BarBasis/NativeBarSpec/BoundarySchedule, explicit unknown-provider
  handling, boundary validation and per-purpose native capabilities. Platform
  v2 providers declare their basis through the validated channel manifest.
- Real UTC/Shanghai/New York day/week/month/12M aggregation using pinned IANA
  2026c rules; DST 23/25-hour days, leap days and exact-source checks.
- Local selectors, qualified labels, capacity limits, streaming SQLite
  composition, frozen manifest validation, history/live repair and warm seed.
- Preservation-first legacy storage isolation, verified complete backup,
  audit and restore-to-new-file command. Old OHLCV is never relabeled.
- Host-neutral Pine boundary patch, native backtest/replay and indicator
  sessions. Published engines fail clearly when the new capability is absent.
- All 30 catalog locales include the anchor/calendar controls and limits.

Architecture, supported ranges, migration commands and provider matrix:
[boundary contracts](../architecture/ISSUE_117_BAR_BASIS.md).

## Automated and runtime results

Counts below are separate suites and overlap; do not add them as unique cases.

| Check | Result |
| --- | --- |
| Backend core intervals, aggregation, routing, history, storage and CCXT | 217 passed |
| Final calendar, generic CCXT, local API and Twelve Data contract regressions | 92 passed |
| Local service/API/calendar/migration regression | 46 passed; later added calendar cases included in the 92-case suite |
| Legacy migration/rollback and frozen-definition regression | Passed; isolated SQLite only |
| Plugin provider/core, historical contracts, storage identity, warm start, gaps and quality | 64 passed |
| Pine runtime Rust library | 2,328 passed |
| Actual candidate Python API, boundary aliases and realtime sessions | 59 passed |
| Pine bridge / native session regression | 12 passed |
| Real native calendar + fixed anchors + backtests + replay | 18 passed |
| Indicator service / Pyne removal guards | 25 passed |
| Full frontend functional suite | 4,440 passed |
| Drawing performance gate, isolated by frontend runner | 1 passed; p95 0.811ms |
| TypeScript, ESLint, architecture, 30-locale validation, web build | Passed |

The calendar JSON asset lives in `frontend/data/` to preserve the source-only
architecture rule without adding an exception. Backend/frontend rule copies
were checked equal after relocation.

The initial full frontend run found a wrong argument type passed to the local
interval composability helper. It was fixed, targeted tests passed and the
full suite reran successfully. Its initial performance failure occurred during
compilation; the final isolated gate passed. Two iterations of a new indicator
test used incorrect SDK result field names; the corrected test passes against
the actual candidate, including forming replacement, append and history repair.
The final integration pass exposed a legacy test expecting unqualified rows in
the active table and a missing declaration path for external providers. The
test now checks preservation in the legacy table; providers can declare their
basis in the manifest. History/live integration passes, and absent or malformed
declarations are rejected. Two new test assertions were corrected to use the
actual error-code and normalized-event fields before the final 64-case pass.

Native DST oracle: independently generated New York local-date edges, hourly
input across March 2024, actual `time_close`, same-period and 2D security,
seek/snapshot/play, process reopen/restore, final result equality. Calendar
indicator tests verify stable boundary identity across appends, native session
reuse and reset/replay after a historical correction. The engine patch also
checks malformed windows, missing cross-timeframe windows and `D`/`1D` aliases.

The candidate source/patch/wheel digests and release status are recorded in
[pine-candidate.json](issue-117-evidence/pine-candidate.json). The wheel was
installed only into `output/issue-117/calendar-runtime`; published release locks
and the existing qualified runtime were not modified.

## Actual browser and network evidence

The local development UI imported 720 synthetic hourly CSV rows for March
2024. Switching UTC → New York changed actual last-bar OHLC from
`796/822/795/821` to `776/802/775/801`. Reload retained the New York identity and
OHLC. [Browser receipt](issue-117-evidence/calendar-ui-proof.json); screenshot
is retained locally at `output/issue-117/calendar-restored.png`. This is browser
development acceptance, not native packaged acceptance.

OKX Spot and Swap each produced an actual closed 1m candle. Their actual socket
transport was aborted and the **same CCXT instance** reconnected, received a
new raw candle and showed a second connected lifecycle event. Expected network
errors were observed and recovered. [Reconnect receipt](issue-117-evidence/okx-close-reconnect.json).
The earlier 28/28 matrix received data for Spot/Swap × 1m/6h/12h/1d/3d/1w/1M ×
two connections; these samples were forming and are not long-period close
certification. Script: `backend/scripts/verify_okx_basis_live.py`.

Bybit public spot 5m REST returned HTTP 200; the capture is a regression fixture
validated through the generic normalizer. Twelve Data early-close acceptance
uses a deterministic session fixture; it is not a new live-provider test.
[REST observations](issue-117-evidence/rest-basis-network.json).

## Remaining release / external acceptance

- OKX historical REST on this machine timed out (an earlier probe returned
  HTTP 403). Offline routing/normalization passed; live historical REST remains
  unqualified. Do not close this network gap based on WS success.
- Calendar Pine is an unpublished local engine candidate. Publish/version the
  engine and qualify runtime bundles on supported platforms before claiming a
  general installed-runtime release. It is separate from the Renko candidate.
- Desktop packaging acceptance is intentionally deferred by the user.
  A draft PR was subsequently requested for review. Its automatic desktop
  packaging CI does not substitute for the deferred manual desktop acceptance.
- Unknown generic venues, arbitrary local cutover times, subminute anchors and
  session-to-continuous derivation are explicitly unavailable, not silently
  approximated or claimed as universally supported.
