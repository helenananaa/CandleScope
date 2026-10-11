# macOS desktop packages

The `macOS desktop` Actions workflow builds native packages separately on
`macos-15` (Apple Silicon / M1 and later, `arm64`) and `macos-15-intel`
(`x64`). A native build is required: Electron, standalone CPython 3.12 and all
Python extension wheels must match the same architecture. These are not
universal binaries.

## Download

Open a successful workflow run in GitHub Actions and download the
`CandleScope-macos-<architecture>-<commit>` artifact. It contains a DMG, a ZIP,
`SHA256SUMS`, and `build-manifest.json` identifying the exact source commit.
Artifacts expire after 14 days. A workflow run does not publish a GitHub Release.

Choose `arm64` for M1/M2/M3/M4 and other Apple Silicon Macs; choose `x64` for
Intel Macs. Mount the DMG and copy CandleScope to Applications, or extract the
ZIP and move the app to Applications. Python and backend dependencies are
included, so no system Python, Node.js or development checkout is required.

These are **ad-hoc signed test builds**, without an Apple Developer ID
signature or notarization. macOS may block their first launch. Review the source
and artifact checksum before deciding whether to allow the app through macOS
Privacy & Security. The workflow does not disable Gatekeeper or install signing
credentials. Production distribution needs a separately approved signing and
notarization setup.

## Build on a Mac

Install Node.js 24 and uv, then from `frontend`:

```sh
npm ci --ignore-scripts
npm run check
npm run desktop:package:mac -- --arm64  # Apple Silicon host
# npm run desktop:package:mac -- --x64 # Intel host
```

The original `npm run desktop:package:dir` command remains an unpacked build.
It still enforces the runtime's platform and architecture in `beforePack`.
The macOS command creates a DMG and ZIP and explicitly disables publishing.

## Verification

Both Actions jobs run the complete frontend `npm run check`, including
architecture, plugin contract, i18n, TypeScript, lint, frontend tests, desktop
host tests and a production frontend build. They then package the app, extract
the final ZIP into a different path containing spaces, validate Electron/Python
Mach-O architectures, reject symlinks outside the app, import the bundled
Python dependencies, verify the app signature and DMG, and launch/restart the
relocated app with isolated user data. The smoke checks the real sidecar health
endpoint and live, replay and strategy page entrypoints. Reports and screenshots
are uploaded separately as `macOS-evidence-*`.

This smoke does not validate live exchange availability, full replay/backtest
correctness, first-launch Gatekeeper approval, or an Apple-notarized installation.
The backend's complete pytest and optional plugin package suites are separate
from this packaging job.

## Pine / Pyne plugins

Desktop packaging preserves the existing plugin installation model. It bundles
the plugin SDK, not the independently released Pine/Pyne engines or plugin
bundles. Pine runtime v0.3.2 provides separate macOS `cp310-abi3` wheels for
`arm64` and `x86_64`, but a runtime wheel alone does not make the current
Windows-targeted CandleScope plugin bundle a supported macOS bundle. A macOS
plugin release, its platform metadata and the corresponding engine version
must be validated together before advertising Pine/Pyne support in this app.
