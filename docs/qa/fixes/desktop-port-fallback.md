# Desktop startup with occupied ports

## Cause and change

The desktop sidecar previously bound the configured backend port (normally 18080) and failed startup if another process already owned it. The renderer also derived its API endpoint from that preferred port. A healthy unrelated service must never be reused as the desktop backend.

- The bundled Python sidecar now binds the preferred loopback port itself. Address-in-use or permission/reservation conflicts fall back to port 0, letting the OS choose a free port. The same socket is passed to Uvicorn, so there is no probe/close/rebind race.
- The sidecar announces its assigned port and per-launch instance ID through a unique temporary endpoint file. The supervisor validates both the announcement and the health response identity, then removes the file. Startup failure also removes announcement artifacts.
- The host passes the actual port to every chart and auxiliary window through Electron arguments. The preload rejects missing/invalid endpoints instead of silently falling back to another service. HTTP, WebSocket and plugin management use the resolved endpoint.
- The packaged asset server likewise retries port 0 if its preferred port (normally 18079) is occupied. Its trusted origin and backend CORS/management origins follow the actual listener.
- Explicit custom sidecar commands retain their existing endpoint contract. No unrelated process is stopped to make room.
- After the first healthy startup, the supervisor pins the backend port for that desktop session. A sidecar restart binds this exact port, keeping existing windows and plugin-management requests on the same endpoint. If another process takes the port during downtime, restart fails explicitly; releasing the port permits retry. Only a fresh desktop session may choose another fallback port.

## Validation

- 60 desktop tests passed, including occupied asset-port fallback, all native window endpoint arguments, preload validation, dynamic endpoint discovery/restart/cleanup, and rejection of mismatched announcements.
- 8 Python tests passed, including occupied-port fallback, held-socket exclusivity, preserving an available preferred port, invalid-port rejection, actual Uvicorn HTTP service over the announced socket, and graceful parent-pipe shutdown.
- The desktop API test passed for replay/backtest HTTP and WebSocket URLs using a non-default backend port.
- The packaged `frontend/desktop-dist/port-fallback-20260930/win-unpacked/CandleScope.exe` was launched with an isolated user-data profile while two test services occupied 18079 and 18080. It selected UI port 14010 and backend port 14032. The native UI showed 1501 candles and connected Binance/WebSocket status; backend logs confirmed successful chart, plugin-management and replay-hub requests. Navigation to the strategy page loaded datasets/presets successfully. The two occupying services still returned their original marker responses.
- Closing the native app completed backend shutdown and released both assigned ports. The test occupier was then stopped and all four ports were verified released. Endpoint announcement files were removed after readiness. UI evidence: `output/desktop-port-fallback-ui.json`; runtime log: `output/desktop-port-fallback-profile/logs/backend-sidecar.log`.
- The desktop production build and packaging completed successfully. Existing bundle-size advisory remains. Source syntax and whitespace checks passed. Additional native-window argument propagation is unit-tested; this packaged UI check navigated the primary window and did not run a multi-window stress scenario.

## 2026-09-30 pre-commit follow-up

- Desktop tests: 60 passed, including stable endpoint reuse across restart, rejection when the session port is occupied, cleanup, and recovery on retry.
- Python sidecar tests: 13 passed, including real Uvicorn service on a pinned session port, rejection of invalid pinned ports, and refusal to announce a replacement for an occupied session port.
- A live Node supervisor/Python-Uvicorn integration check also passed: occupied preferred port -> fallback -> stop/restart on the same endpoint -> occupied session port rejection -> successful retry after release. Both unrelated HTTP listeners kept their original responses. This used a minimal ASGI app, not a native-window F2 run.
- Related frontend tests: 364 passed across market data, the shared indicator coordinator, i18n, and desktop API URL routing. The Portuguese checker now recognizes the case-sensitive `Home` key label while retaining a regression assertion that lowercase English `home` is rejected.
- Production frontend build passed with the existing large-chunk advisory. No new native package was built for this follow-up; the packaged UI evidence above predates the session-port pinning change.

## Boundaries

Browser origin storage is scoped to the UI origin: an asset-port fallback changes that origin. This change does not migrate origin-local browser storage between UI ports; existing data under the original origin is not deleted. Backend-port fallback alone preserves the UI origin. An origin-stable desktop storage migration is separate work.

The unpacked QA build includes unrelated working-tree changes and is not a signed installer/release artifact.
