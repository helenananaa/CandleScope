# #166 replay display sequence entry

The production replay display path uses the common MarketDataManager lifecycle core, with private sequence leases keyed by run/track/session/epoch/generation/period. Server display and tape projection/history requests share that ownership boundary. The existing source/reveal and financial contracts are retained. The replay root cannot import live transport code; architecture checks pass without allowlist changes.

Validation: full `npm run check` passed (4,673 frontend tests, one isolated performance gate, 124 desktop tests, architecture/plugin/i18n, TypeScript, lint and production build). Existing effect-cleanup and chunk-size warnings remain. Targeted checks cover independent windows/runs/live cache, ignored-abort responses, same-identity reacquisition, source identity changes and shutdown.

Ten real Chromium replay fixture cases passed, including continuous tape playback, rewind, independent history/viewport, canonical indicators and the production provider under StrictMode. Diagnostics prove managed requests and identity; final unmount removes the provider handle. No renderer exception or retained Worker. The minified fixture uses development React act and controlled replay transports. It is not installed-package acceptance.

The local driver required a 60-second startup allowance after its original 10-second browser-port-file deadline failed before fixture execution. Only that wait was changed in a temporary driver; product and fixture assertions were unchanged. The copy, full browser receipt and full check log are preserved under `output/replay-sequence-entry-20261031`. Adjacent checks.json summarizes the accepted run; source-manifest.json records SHA-256 inputs.

Run-level controls, canonical source streams/other APIs, backend DataManager integration and native save/full-exit/restart acceptance remain open. This first phase does not close #166 or certify any complete dual-Manager checklist item.
