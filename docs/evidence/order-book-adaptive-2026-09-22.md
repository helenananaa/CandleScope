# Adaptive order-book grouping — 2026-09-22

## Delivered behavior

1. Shared 1–2–5 tick candidates (full: 1 through 1000; bounded Top-N: 1 through 10).
2. Viewport row targets and near-price occupancy select one step for both sides. The near-price inspection horizon defaults to 10 bps, bounded to 512 raw levels per side; small books prefer raw precision. This is a heuristic over available data, not unseen exchange liquidity.
3. Per-view hysteresis: at least 0.25 score improvement, 2 seconds sustained preference, 5 seconds between step changes. Browsing away from either best quote freezes automatic step changes.
4. Independent range choices (uncapped, 0.05%, 0.1%, 0.25%, 0.5%, 1%) and output count. Coverage labels use the delivered outer prices relative to the raw midpoint; spread and bucket rounding can make these differ from the requested side range.
5. Negotiated display commands update presentation without reacquiring the source lease. Raw quotes/spread and source liquidity remain authoritative. Projection cache identity includes the resolved step, target rows and range.

## Verification

- Backend: 51 passed across `test_order_book_auto.py`, `test_full_order_book_api.py`, `test_full_order_book_stream.py`, `test_order_book_api.py`, `test_order_book_stream.py`.
- Frontend: 18 passed in `src/features/order-book/__tests__/*.test.*`.
- Backend Ruff, targeted frontend ESLint, full TypeScript check, i18n catalog check, and `git diff --check` passed.
- Production build passed from the physical checkout `E:/Disk0Merged/H/program/CandleScope/frontend`. Running from its mapped H: alias first failed with a Vite absolute emitted-path error; no build configuration was changed.

## Browser observations

A temporary, explicitly labeled deterministic fixture used 2000 synthetic levels per side around 60000, tick 0.1, and 250 ms updates. It exercised the actual Python WebSocket delivery/serializer, frontend controller/store, and OrderBookDock. The temporary fixture and its servers were removed/stopped afterwards.

| Interaction | Observed result |
|---|---|
| 440 px panel, uncapped range | Auto step 10; measured per-side viewport about 130 px |
| Scroll bids away from best quote | Browsing lock appeared; step held at 10 |
| Enlarge panel while browsing | Step remained locked |
| Return to best quote, 640 px panel | Auto settled at step 5 |
| Select 0.05% range | Auto settled at step 2; delivered coverage −0.050% / +0.053% |
| Change output from 100 to 20 | Same selected range, step and coverage |
| Select manual 2× tick | Step 0.2; raw spread stayed 0.1 |

The temporary development harness emitted duplicate-createRoot warnings during hot reload; this was harness lifecycle behavior, and this run is not a clean-console qualification of the full application. No live upstream exchange session, production rollout, or long-duration soak is claimed.
