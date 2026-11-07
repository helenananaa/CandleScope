# Practice committed updates: current-main native qualification

PR #223 previous heada67fa0b8 is integrated with actual main #2667acba72e and explicit dependencies #26853c581ca (catalog I/O ownership) and #269e7d762ff (serialized-volume normalization). No dependency was silently relabelled as prior #223 source. Product mergecfae61a2, fresh checks83046bf6, Native candidate502d8148. The entire backend/app, frontend and packages trees are equal between the checks and candidate; intervening commits only add QA helpers. Original application cancellation ownership and committed account-view protocol remain intact.

## Source and local checks

Fresh single63-suite backend invocation: **876 passed, one Windows CRT-only skip, six existing warnings**. It combines the prior practice/application/SQLite cancellation, continuous, imported BAR/note/multi-market and related source lifecycle suites with catalog and numeric-volume coverage; no overlapping runs are added together. Full frontend check: **4897 regular + one independent performance +130 desktop tests, zero skipped**; architecture/plugin/i18n/types/lint and production build pass. The existing SingleChartPanes lint warning and large-bundle hint remain.

The first command-preparation script looked for the numeric receipt under checks.json instead of delivery.json and stopped before tests. The corrected preparation consumes delivery.json; the authoritative checks.json records the actual63-suite command. This is not a product test failure.

The current source uses the pre-Pine-domain SDK/bridge family. Its source-verified wheel bundle is f9a075b9..., not the newer95037 bundle from pending #227. A signed retained physical runtime was independently checked before copying; all76 relevant wheel source files match the target checkout. The assembler resolves source paths, rejects existing destinations, creates a physical APFS copy, installs current tracked backend and SDK mirrors, compiles backend, repacks the fresh frontend/current desktop and signs strictly. It reuses qualified dependencies/compiled engines; this is not a full installer/runtime rebuild.

All1065 source/SDK fingerprints,164 built assets,9 plugin assets and76 plugin-source files match before, between and after both Native launches. No original app, profile or source worktree is overwritten.

## Actual Native LIVE proof

A new isolated macOS profile runs the actual packaged app and ordinary public BAR/source and practice routes, without controlled response replacement. The test creates two explicit simulated accounts with1000USDT, buys0.001BTC through the UI, pins account A to the chart, and observes its real entry line. Account B remains independent. A separate local client submits a working limit order, cancels it and closes the position, while the real renderer adopts committed account snapshots.

During the uninterrupted22149ms push phase, the chart's pinned A and panel's selected B each retain exactly one renderer stream without reconnecting. A receives its commits; B remains1000 with no trades or positions. The closed A entry line disappears and both fill markers appear. All renderer requests across the two launches contain zero legacy summary/trades/journal polling. Independent observers validate replacement identity, ledger epoch and ordered sequence.

Source/settings and trade records save, the app exits completely, then the same profile restarts. Exact fills and financial views return, account A remains pinned and its trade markers restore. The ledger cursor remains epoch15c45e.../sequence15. Releasing the last renderer consumer closes its stream; reopening creates exactly one new stream and restores the same view. The restored whole-window screenshot includes markers and selected account; some account details are below the sidebar fold, so financial precision is established by the actual renderer model, API/fill data and the cold SQLite witness, not that screenshot alone.

The independent post-exit audit imports no application mathematics. From captured account settings, each fee equals price×quantity×0.0005; the two actual fills are75847.35×0.001 with fee0.037923675 each. Both saved and restored views equal **cash/equity999.924152650, net PnL-0.075847350**, no positions or working orders. A read-only SQLite transaction confirms all recorded fill fields, the two filled/one cancelled order statuses, initial cash1000, persistent cursor and quick_check=ok. The retained Python audit reproduces these assertions. These prices are the observed practice reference inputs; no new orderbook parity/live quote freshness qualification is claimed.

Both exact sidecars exit0/signalnull, without any kill request. App close times2340/2231ms. All20 app-owned PID entries independently disappear. The broader runner observes37 descendants including verifiers/oracles; these are not relabelled as37 app processes. No renderer errors.

## Delivery boundary

This qualifies the recorded macOS practice UI/shared-versus-pinned committed-view/spot-ledger/save/normal-exit/restart scope for this explicit main266+268+269 combination. It does not complete full #177, multi-instrument/HEDGE, Native OCO matching, resumable row-delta journals, Windows, whole-product live freshness or a release installer. Existing controlled HTTP OCO and lifecycle evidence retain their own source/scope. No new Pine capability or #227 recovery claim is imported.

Original #223/#218 worktree heads, complete porcelain statuses with all untracked files, and84 dirty-file fingerprints remain unchanged. The initial preservation comparison used normal untracked-directory grouping; matching the recorded --untracked-files=all format verifies the exact original statuses. All old Native profiles/apps and evidence remain retained. No new cleanup is claimed in this receipt.

PR #223 can move to review with explicit #268/#269 dependencies and the above limits. CI remains in the background; main merging requires a fresh audit of final head/current main, applicable checks and product scope. Continue #218 independently. receipt.json indexes raw commands, helper source, source/build fingerprints, screenshots, financial and process receipts by SHA-256.
