# Live chart date navigation — macOS native evidence

Source: `7b173ff8edc1a8b5b5a346ccb0a926108b395540` (PR #196), macOS arm64, official ZIP extracted into a fresh installation. The bundled backend, application HTTP/WebSocket, and production renderer ran without response substitution. This is a finite scenario qualification, not the full acceptance matrix or Windows qualification.

The source/package manifest checks 3,110 tracked source files and 165 built distribution files, with no mismatches. ZIP SHA-256: `c331376d7a84e1db762b505772aea878e034eb327fbde2ee511fd20748d94373`; ASAR: `d8744ed6e96362f91f214e55a583196575b47f3b47fe8f8a31d615046971318f`. Strict signature checks passed before use, after navigation, and after restart.

The isolated profile initially contained only 8,000 synthetic 1m rows (two instruments), with no 5m bars. An Alt+G seek to 2023-11-15 14:54 UTC fetched a bounded 501-row 1m window, preserved the 60-bar zoom, centered the requested row, and left the sibling chart on its independent live view. Synthetic 1m OHLC matched the finite fixture. Real live traffic for three seconds did not append the current market tail into the historical view.

With time-anchor linking enabled and the sibling switched to 5m, the first seek disclosed partial unavailability. The second explicit UI retry succeeded. Each chart centered its own interval's target; the original 1m chart retained its zoom. The 501 displayed 5m rows exactly matched time/OHLCV returned by the bundled backend's strict, repair=none range query, which reported complete/ready. These 5m rows were fetched from the real provider, not computed from the synthetic 1m oracle. No 5m data was preseeded to bypass cold repair.

The application and all owned descendants exited normally (15.288 seconds). A fresh process restored both chart intervals and link policy. Reopening the live workspace currently starts at latest data; it does not persist the historical navigation window. A new historical jump after restart succeeded for both periods, and the active chart's “回到实时” control restored current data. The second normal exit and strict signature check also passed. Both receipts contain no renderer errors.

This fixes the earlier cold 5m failure: an old-date head gap incorrectly expanded 501 requested bars to 288,260, then stalled in memory admission. The backend fix is independently submitted as PR #198. The candidate's backend/app, backend dependency manifests, and packages are byte-identical to #198's `b24b54d4a1c432f68eddf90c4d2174cc89477ee0`; the frontend includes the date-navigation integration.

Local full checks passed: 4,721 frontend tests, one isolated drawing-performance check, 127 desktop tests, architecture/plugin/i18n checks, both TypeScript projects, lint and production build. The relevant backend gap/calendar/coordinator/audit selection passed 129 tests. Exact-head cloud CI is still required before merging main.

The compact receipts and file manifest are in this directory. Full traffic, screenshots, raw receipts, private profile, and retained ZIP are under `output/issue186-bounded-history-native-20261101` in the development worktree. The earlier failing candidate remains recorded under `output/issue186-viewport-fixed-native-20261101`; its failure was not replaced with this pass.

Remaining issue scope: other replay modes, local imported data navigation, broader calendars/timezones and boundaries, and native rapid-request cancellation scenarios. This increment does not close #186. The current branch also contains earlier PR #180/#192 changes; separate replay and style acceptance remains required for their final integrated heads.
