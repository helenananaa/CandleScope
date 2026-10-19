> Integration update: start the desktop app, open Settings > AI connection, opt into desktop workflow tools and explicitly select Read or Control. Startup flags do not enable access. Copy the JSON/TOML stdio configuration from that panel. Revocation and mode changes close both transports; restarting always returns to Off. Earlier launch examples below are historical and are superseded by this flow.

# CandleScope control

Local CLI and stdio MCP adapter for a running CandleScope **desktop** window. Node.js 22 or newer is required. It shares the application's workspace actions; it does not automate mouse coordinates or start a second app instance.

See [the setup, command contract and validation guide](../../docs/agent-control.md).

```powershell
cd packages/candlescope-control
npm ci --ignore-scripts
node cli.mjs help
node cli.mjs capabilities
node cli.mjs inspect --window main-window
node cli.mjs commands --window main-window
node cli.mjs query --params-file query.json
node cli.mjs execute --params-file execute.json
node cli.mjs upload --window main-window --file candles.csv
node cli.mjs download --window main-window --id FILE_REF --out report.json
node cli.mjs mcp
```

The default connection file is `%APPDATA%/CandleScope/control/connection.json` on Windows. If your application profile differs, supply `--connection FILE` or `CANDLESCOPE_CONTROL_FILE`. It contains a credential: do not copy it into prompts, logs, repositories or MCP configuration.

```powershell
npm test
# Build frontend/dist first. Launches and closes its own isolated Electron profile.
node desktop-smoke.mjs
```

The native smoke uses synthetic bars, import/project and strategy-job responses, and WebSocket acknowledgements. It validates the MCP-to-renderer path, command discovery, persistence/indicators, stale-state rejection, watchlists and drawing history, lazy panels, chart export, bounded file transfer/hash/window isolation/reload expiry, CSV upload through the library workflow, strategy drafts/run-cancel protocol, managed pages and capture. It does not qualify real strategy execution, CSV backend algorithms, replay trading, live orders/exchanges or packaged releases. See [the coverage inventory](../../docs/agent-control-coverage.md).

```powershell
# Build frontend/dist first; requires a backend Python environment and an installed native strategy engine.
node real-backend-smoke.mjs
```

The real-backend acceptance starts the existing replay smoke bootstrap in isolated storage with deterministic market rows and a loopback network guard. It uses production local-data, strategy and replay services without business-response stubs. All business actions originate from stdio MCP; separate HTTP reads verify CSV rows/quality, project restoration, native execution/cancellation and reports. Replay creates a run, selects the initial market, buys/sells, ends training and checks its account audit and exported report. It writes success/failure receipts, build hashes, logs and screenshots to `output/control-real-backend/` and closes its isolated processes/profile credential.

Python selection: `CANDLESCOPE_QA_PYTHON`, then `backend/.venv/Scripts/python.exe`, then the prepared desktop Python runtime, then `python` on PATH. The native registry is copied from `%LOCALAPPDATA%/CandleScope/plugins/native-strategy-registry.json`; override with `CANDLESCOPE_QA_NATIVE_REGISTRY`. The registry must reference installed engine environments. This exercises those installed versions, rather than source changes to plugin packages. Approximate BAR/ONE_WAY training is qualified; exchange access, live orders, historical-exact/hedge execution and packaged release installation remain separate acceptance tasks.

Ordinary editing and file transfer require --control-edit. Trust changes additionally require --control-trust; live execution additionally requires --control-live. Both are disabled by default and retain backend permissions, previews, confirmations and risk checks. Files are window-bound, at most 32 MiB each/128 MiB total, with 32 KiB chunks, and expire on reload/close or after 30 idle minutes. Downloads verify SHA256 and refuse to overwrite an existing file.
