# #166 replay sequence and run operation entry

The production replay display path, run controls and canonical adapter streams use the common MarketDataManager lifecycle core. Charts retain private display windows keyed by run/track/session/epoch/generation/period. Run-entry and viewer operations own full parsed HTTP requests; each pooled adapter owns its HTTP and stream lifecycle. Operation leases contain no account/order state or rows. Existing source/reveal, command retry/envelope and financial contracts remain in the adapters and API clients. Architecture checks pass without a live-transport allowlist exception.

Full `npm run check` passed: 4,677 frontend tests, one isolated performance gate, 124 desktop tests, architecture/plugin/i18n checks, TypeScript, lint and production build. The existing SingleChartPanes cleanup-ref warning and bundle-size warnings remain.

The new regression cases cover cancellation after HTTP headers but before body decoding, isolation between runs, same-identity reacquisition, external cancellation, stream stop/reopen and heartbeat fencing, cleanup failures and adapter startup/restart/disposal. The real command API's bodyless-5xx test verifies that the managed operation preserves its one retry and byte-identical command envelope.

Eleven real Chromium fixture cases passed. The added case mounts the production provider and operation hook under StrictMode, checks that selecting another adapter preserves an in-flight run operation, switches runs, rejects old completions/frames, and verifies final unmount removes operations and the diagnostic handle. Existing cases cover continuous tape playback, rewind, canonical indicators and independent history/viewport. No renderer exception or retained Worker. The minified fixture uses development React act and controlled replay transports; this is not installed-package acceptance.

The browser driver retained the prior local 60-second startup allowance instead of its original 10-second port-file deadline. Only that wait changed in a temporary driver; product and fixture assertions were unchanged. The temporary script was removed. Full logs, driver and browser receipt for this extension are under `output/replay-run-operations-20261031`; prior display-phase evidence remains in `output/replay-sequence-entry-20261031`. Adjacent checks.json records results, and source-manifest.json identifies the tested inputs.

## Remaining API entry extension, 2026-11-01

Hub/initial-market, review/rail, account records, public time, history/tape, canonical indicator computation and NDJSON export now enter manager operations. Run context reaches nested consumers; the live workspace capability check uses its existing replay namespace. Constructors remain inert. Existing physical history sharing is preserved, and the manager owns retry backoff as well as response decoding.

The complete local check passed with 4,682 frontend tests, one isolated performance gate and 124 desktop tests. Eleven real Chromium fixture cases passed with no exceptions or retained Workers; the operation fixture now exercises inherited run context under StrictMode. Added unit cases cover opening Hub creation before list startup, ignored-abort completion after Hub disposal, independent consumers sharing a physical history read, release during retry backoff, the full NDJSON response body, and cancellation of partial canonical script results. Final TypeScript and targeted lint were rerun after the last capability-binding cleanup.

`output/replay-remaining-api-20261101` holds logs and the browser driver/receipt. The only driver adaptation remains the 60-second startup allowance. Adjacent checks and source manifest reflect this extension. Controlled transport coverage is not installed replay-package qualification. The separate #178 live JS package acceptance cannot qualify replay #180.

Backend DataManager integration and replay native save/full-exit/restart acceptance remain open. This frontend phase does not close #166 or certify the complete dual-Manager checklist. CI is not awaited for development; exact-source CI and native qualification remain required before a main merge.
