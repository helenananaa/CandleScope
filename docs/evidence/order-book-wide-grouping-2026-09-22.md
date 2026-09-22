# Wide manual order-book grouping — 2026-09-22

This follow-up supersedes the manual multiplier cap and edge-omission behavior in the earlier adaptive-grouping evidence. Source acquisition limits were not increased.

## Behavior

- Both snapshot and continuous modes accept 1–2–5 tick multipliers through 1,000,000,000. Auto retains its previous conservative caps. Tick 0.1 supports manual steps including 1000, 2000, 5000 and 10000 quote units; tick 0.01 also reaches 10000 with multiplier 1000000.
- Aggregated bids display `[lower, upper)`; asks display `(lower, upper]`. Every known quantity remains in its bucket, including a lone partial bucket. A zero lower bucket boundary is valid; a zero raw quote remains invalid.
- Seed-derived trusted bounds are carried through immutable engine snapshots. Sparse outer updates do not enlarge them. Retention trimming shrinks bounds; resynchronization replaces them. Unknown provenance fails closed as unconfirmed coverage.
- Partial bucket quantities show `≥`; cumulative values remain lower bounds after an incomplete interval. Raw known quotes remain exact, but their cumulative values also become lower bounds if they cross unobserved gaps.
- Displayed coverage percentages intersect the delivered price range with trusted bounds. A 10000-wide bucket cannot suggest 10000 of source coverage merely because of its label.
- Old omission flags remain false for wire compatibility. `full_projection` continues to describe local projection completeness, not exhaustive exchange depth.

## Tests

Backend: 151 passing tests across full-book engine, API, stream, service, runtime, data-manager, adaptive selector, and partial-book API/stream suites. Frontend: 21 passing order-book tests. Checks cover quantity conservation, complete versus partial buckets, absent provenance, projection truncation, safe zero bounds, immutable seed bounds, retention shrinkage, and reseeding.

Ruff, frontend ESLint, i18n (30 locales), TypeScript, production build and whitespace checks are recorded in the task tool results. Production builds use the physical E:/Disk0Merged/H/program/CandleScope/frontend checkout to avoid the existing H: alias/Vite path mismatch.

## Browser evidence: synthetic fixtures, not live exchanges

Used the real Python WebSocket serializer plus the real frontend stream controller and OrderBookDock, with explicitly labeled synthetic BTC and ETH books. Each side contained 1000 known levels. Temporary servers/pages were stopped and removed afterwards.

| Fixture | Tick | Selected step | Trusted bounds | Observation |
|---|---:|---:|---|---|
| BTC around 60000 | 0.1 | 10000 | 59900.1–60100 | Ask interval (60000,70000] shows ≥2000; bid partial interval [50000,60000) shows ≥999, cumulative ≥1000; coverage stays about ±0.167% |
| ETH around 3000 | 0.01 | 1000 then 10000 | 2990.01–3010 | Large steps selectable; zero-lower-bound intervals remain live; ask ≥2000 and bid ≥1000 at step 10000; coverage about ±0.333% |
| ETH restored to raw | 0.01 | 0.01 | 2990.01–3010 | Raw precision and spread 0.01 restored |

The temporary harness emitted a duplicate-createRoot warning during development hot reload, followed by an explicit page reload. This is not a full-application clean-console or live-market qualification. This change does not backfill the unknown far book or claim exhaustive exchange liquidity.
