# OI local history: main266 native qualification

PR #218 previous head9a204224 is integrated with main #2667acba72e and explicit dependencies #26853c581ca (catalog I/O ownership) and #269e7d762ff (serialized-volume normalization). The merge chain is47725aab3/4bd98415f/508d6f46a. Checks run atd40cc620; actual Native candidate and driver are774ed16d. Entire backend/app, frontend and packages trees match between these sources; intervening changes only strengthen QA. No Pine-domain SDK or unqualified #227 capability is imported.

## Local checks and package identity

One fresh72-suite backend command: **1031 passed, one Windows CRT-only skip, six existing warnings**. It combines OI/source/history/aggregation/replay/continuous lifecycle coverage with catalog and numeric-volume suites; overlapping runs are not added together. Full frontend check: **4894 regular + one independent performance +130 desktop tests, zero skipped**; architecture/plugin/i18n/types/lint and production build pass. Existing SingleChartPanes lint and large-bundle hints remain. Exact commands/environment and output are archived in receipt.json.

The physical app is cloned from the retained qualified main266 #223 runtime. The copier resolves the source and rejects an existing or dangling destination. It installs current tracked backend and SDK mirrors, compiles backend, repacks freshly built frontend/current desktop ASAR and signs strictly. Relevant runtime dependencies and engine sources match; all76 plugin-source files match the target checkout. The pre-Pine bundle is f9a075b9..., distinct from pending #227's newer95037 bundle. All1065 source/SDK,164 built and9 plugin asset fingerprints match before/between/after Native, with strict signature verification. This uses qualified runtime dependencies and compiled engines; it is not a full installer/runtime rebuild.

## Actual Native LIVE result

A new isolated macOS profile runs the actual packaged backend, renderer and ordinary public Binance futures inputs, without API substitution or injected pane data. All28 recorded stages pass, with zero renderer errors.

For BTCUSDT5m, a bounded4h historical query returns an empty/incomplete local-only result first. fill_missing acquires48 actual source records and a durable bounded-query receipt. Repeated hot fill_missing and local_only preserve full data and receipt observation timestamps. Explicit refresh records a new source observation; subsequent local_only remains stable.

The actual OI study draws a blue curve and visible source/finality labels before quit and after same-profile restart. The observational probe captures actual MarketPaneLabel props and DOM text:120 points before the first exit,500 after restart. It does not replace inputs or synthesize a model. The independent audit imports only Python standard-library JSON/SQLite code: all48 requested records match every cold SQLite field across full exit/restart, and **each requested event/value matches the actual500-point restored line**. SQLite quick_check=ok. Query receipts and persisted study settings restore unchanged. Screenshots saved-oi-pane-values.png and restored-oi-pane.png show the actual pane.

Both exact sidecars exit0/signalnull, with no kill requests. Close times3008/2988ms. All20 app-owned PID entries independently disappear. The broader runner observes36 descendants including verifier/SQLite helpers; these are not relabelled as36 app processes. The app remains strictly signed and source fingerprints remain unchanged after shutdown.

## Scope and preservation

This qualifies the recorded bounded Binance futures5m OI local-first/query-receipt/actual-plot/save/normal-exit/restart scope on main266+268+269. The48 observed source event times are all5m-aligned: this Native sample supplies no new non-aligned timestamp proof; component counterexamples retain their own scope. Initial120 versus restored500 points reflects asynchronous pane hydration; no claim that all1500 Kline-visible points were covered before the first quit. Labels may follow crosshair or provisional live updates, so they are not asserted equal to the last historical point. General Kline live-wait/orderbook connection status visible in screenshots is outside this bounded OI qualification. Full #149, every exchange/period, whole-product live health, Windows and release-installer qualification remain open.

The Windows tool gateway returned429 before a host command; this is neither a Windows product failure nor a pass. Both original dirty #223/#218 worktree heads, complete porcelain statuses (--untracked-files=all), and84 dirty-file fingerprints are checked separately and retained. Original apps/profiles/data and earlier failed evidence are preserved.

PR #218 can move to review with explicit #268/#269 dependencies. CI continues in the background; a main merge requires a fresh final-head/current-main/applicable-check and product-scope audit. Continue #249 independently. receipt.json indexes commands, manifests, lifecycle records, screenshots and the independently reproducible cold/plot audit by SHA-256.
