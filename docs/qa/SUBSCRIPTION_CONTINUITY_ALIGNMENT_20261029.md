# Subscription continuity alignment with PR #145

PR #148 now builds on `66898df0` from #145. The common OKX control-message,
physical interruption, stale-generation and forming-bar repair fixes belong
to #145; this PR retains subscriber strict/gap-aware policy and recovery.

Ingestion construction preserves both pre-registered callbacks and the gap
repair owner. Provider fixtures follow declared market and BarBasis capability
instead of implying support for unqualified intervals. Source-component
recovery follows #145's injected DataManager reader.

The final combined subscription, consumer, delivery, CCXT recovery, source
revision and architecture run passed **252 tests, 0 skipped** in 47.01s with
isolated SQLite directories. Local evidence is retained in the CCXT integration
worktree as `output/ccxt-integration/subscription-owner.log` and `.xml`.
The earlier 184-test subset is not added to this count.

The public-network report `SUBSCRIPTION_CONTINUITY_LIVE_20261029.md` keeps its
original commit/evidence scope; it was not re-executed for this alignment.
PR #148 remains Draft: per-venue ordinary-trade/liquidation recovery capability,
OKX pagination, Bybit bounded-window qualification, UI controls and long/native
acceptance are still open. No default-budget or all-market guarantee is added.

## D126 consumer fixture migration

The cross-draft trial exposed fixtures that notified history completion before
committing the corresponding SQLite rows. Those fixtures now commit first,
and final-history assertions use public queries instead of assuming internal
cache entries remain resident. Alert-history assertions are preserved.
The complete standalone 252-test suite passed again in 54.62s; evidence is in
`subscription-canonical.log` / `.xml` in the same output directory.

This test migration does not fix the separate runtime integration gate:
when the D126 revision fence rejects deferred receipts after a repair, strict
consumers still need an explicit recovery/snapshot notification. Rejection
must continue to prevent stale writes from resurrecting deleted data. The
latest cross-draft trial and exact head identities are recorded in the PRs.
