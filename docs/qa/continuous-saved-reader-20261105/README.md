# Independent saved continuous-account reader

Product source: `9001a26a6ada92fb2d907018333fe53d8f4e4f3d`, stacked on #258 `ddfbbfb6d3b09c4a7d7f0e10d2769e4d88133a4e`.

The actual previous LOCAL_OFFLINE native attempt could not expose the strategy dock behind the study-source mask. Strategy Research now has an independent “保存的常驻账户” header entry. It needs no chart, selected research dataset or editor source, and keeps the study-source mask intact. It observes saved accounts and latest repair status without execution, control or repair commands. Closing the view releases its transport; it does not own the backend execution lifecycle. Exact financial strings and identity-fenced bounded rows share the existing strategy panel renderer. A catalog refresh retains the same observation, selection survives reload, and account switching clears the prior view.

## Local checks

- Final `npm run check` exited 0: **4914** regular frontend tests, **1** isolated performance check, **130** desktop tests; architecture/plugin contracts, 30 locales / 5498 keys, types, lint and production build passed. Existing SingleChartPanes hook and bundle-size warnings remain. `frontend-check-complete.log.gz` is authoritative.
- Focused Strategy Research/account suite: **59 passed** (`research-focused.log.gz`); account/repair SSR focused run: **4 passed** (`focused-final.log.gz`). These overlap the full suite and must not be added to it.
- Backend product code is unchanged in this PR. The predecessor stack recorded **375 passed / 5 existing warnings / 0 skipped**, not rerun here and not full-repository qualification.
- Earlier failed logs remain: incorrect test-helper path; static CSS imports broke Node SSR until CSS moved to the browser bootstrap; fixture navigation before readiness; selector accessible-name mismatch corrected with an explicit label. None of those failed runs is counted as acceptance.

## Actual service and browser

`browser.mjs` runs the actual readonly React component / StrategyDataManager / production HTTP and WebSocket routes / SQLite account / SDK Python using canonical synthetic BARs. The service fixture replaces public market-demand leases, without intercepting account HTTP/WS responses. `browser-final-receipt.json.gz` records three passed flows: exact stale 25-event account; switch to a separate 30-event account with its own full financial identity; same-ID refresh without extra initial reads, close releasing all view observers, reopen/reload remembering the second account. There were zero execution/control mutations and zero browser errors. A 420-pixel view was inspected. Final service shutdown released all leases, closed Controller/store, and all four recorded SDK subprocesses exited; the receipt reports their -9 exit codes. This is not public-feed acceptance.

## Actual arm64 packaged LOCAL_OFFLINE app

`native.mjs` uses the unchanged installed candidate built from the product source above and the previously seeded profile documented in `../continuous-native-20261105/README.md`. No response substitution, chart unmasking or command invocation was used. The full 1280-pixel UI screenshots before and after restart were inspected.

`native-ready-receipt.json.gz` records seven passed stages: source/signature verification, first actual packaged launch, visible account, normal full owned exit, second launch, visible account after restart, second normal full owned exit. Both real UIs show equity **10003**, position **1**, **25** processed events, `REPAIR_REQUIRED`, latest repair `COMMITTED` and the explicit subsequent-history-revision message. Capability HTTP returns LOCAL_OFFLINE with execution disabled. No account control mutations or JS page errors occurred.

- Both full exits were observed: **743 ms** and **608 ms**, with all owned app/helper/backend PIDs absent, including a second process inventory after the test.
- After both exits, the immutable readonly SQLite witness reconstructed and compared the complete saved run, active-epoch definition and checkpoint against the original seed. SHA256 remained `779de17a7cafacec0f0e90743ce29816bce8ffc697e3b37d8e535bec7e3b922c`; witness reads did not change database bytes.
- Before launch and after each exit, **1066 source files**, **168 built files**, **9 plugin assets** matched the package manifest and current source/build; packaged SDK mirrors matched. Deep strict codesign verification passed. The source manifest is archived, not the runtime or profile.

The first driver attempt navigated before desktop startup load completed, aborting that load and opening the real initialization-error dialog. Its failed receipt and main-process sample are retained (`native-*`). The dialog was dismissed and all owned processes were observed exited. A separate cold witness still matched the original seed and strict signature verification passed. The corrected driver waits for startup load and bounds failure screenshots; the successful attempt above reused the preserved profile. The failed first attempt is not accepted as a normal full-exit pass.

## Limits

This qualifies viewing a previously seeded synthetic account in the source-verified local arm64 package, including full exit/restart. It does not qualify creating/executing/repairing continuous market strategies in a LIVE native app, Windows behavior, public exchange data, all #157/#158/#165 requirements, or the unresolved #200 strict restart OHLCV mismatch. Global public retry gates remain in force. Stacked dependency review and exact final-head/base CI are required before main merge.
