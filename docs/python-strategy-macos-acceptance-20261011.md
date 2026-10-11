# Python strategy editor: macOS acceptance

Validated on macOS Apple Silicon on 2026-10-11 using the packaged application installed from the new DMG, with the existing application profile.

## Behavior

- Python source can be edited and run through the existing strategy editor using the bundled SDK and Python runtime. Execution uses a separate process with timeout termination. This is TRUSTED_LOCAL execution with filesystem access, not an OS sandbox; the UI requires confirmation, which resets after source changes and application restart.
- Desktop drafts and strategy workspace state are stored in the application profile, independently of the loopback UI port. The current legacy origin is migrated on first read after upgrade. Writes are queued and atomically replaced; application shutdown waits for pending writes.
- Monaco code, styles, fonts, Python language registration and workers are packaged locally and loaded on demand. Native editing showed the dark theme, line numbers, indentation guides and syntax highlighting.
- For v1 reports without an explicit drawdown metric, the UI derives drawdown from the report's equity samples and identifies this basis. Existing v2 metrics take precedence, and explicitly unavailable metrics remain unavailable.

## Native functional verification

1. Installed the rebuilt ARM64 DMG and verified that the installed `app.asar` hash matched the DMG contents. The previous application was retained as a local backup.
2. Verified migration of the existing Python draft and report. The older report now displays sampled maximum drawdown of 1.09%.
3. Edited Python source to use fast=4 and slow=8 and ran 600 synthetic BTC-USDT / 1m bars. Run `bt_44a2d56567aa4026b8b3dba869a6a4ce` completed.
4. Closed the application, occupied UI port 18079 with a temporary test server, and restarted. The application selected port 51152 and restored the draft, parameters, dataset and report.
5. Edited the source in the native editor on port 51152 and ran again. New run `bt_11e2dd3385a54ecf80d8f72d1d771f97` completed, displaying 29 completed trades, 59 fills, net profit -209.67 USDT and maximum drawdown 1.99%.
6. Removed the temporary port blocker and restarted on 18079. The latest report and 4/8 parameters restored. The persisted draft and research workspace matched the port-51152 snapshot exactly.
7. Independently recalculated both new reports using Decimal arithmetic: the seven equity samples give maximum drawdown 1.987859311%, displayed as 1.99%. This is sampled drawdown, not an intrabar or every-event maximum.
8. Verified that the running backend used the Python runtime inside the installed application.

## Automated validation

- Backtest tests: 190 passed.
- Research data tests: 101 passed.
- Desktop tests: 84 passed.
- Related chart workspace and indicator tests: 364 passed.
- Python editor backend tests: 5 passed, including a real 600-bar subprocess run, confirmation/origin checks, source diagnostics and infinite-loop termination.
- TypeScript checking, targeted ESLint, production build and `git diff --check` passed.
- Total: 744 passing tests. One Starlette/AnyIO deprecation warning was observed.

## Package evidence and limits

- Local package: `frontend/desktop-dist/python-fixes-20261011/CandleScope-0.0.0-arm64.dmg` (approximately 264 MiB).
- DMG SHA256: `7f5ea505a5bb1c703f4065d7feef51763039f3989d31ac6a18f95738ce338692`.
- Installed and DMG `app.asar` SHA256: `958fdbf796cf205edb0133c79473c36b1f9abe924f073e7c79db9d0644c9cf99`.
- Raw run/report JSON, profile snapshots and build/test logs are retained locally under `output/python-mac-fixes-qa/`; generated packages, application backups and profile data are not committed.
- No Developer ID certificate was available. The package has not received Developer ID signing or Apple notarization; local functional acceptance does not establish distribution readiness on other Macs.
