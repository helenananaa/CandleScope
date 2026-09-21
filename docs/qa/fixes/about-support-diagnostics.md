# About & support diagnostics

The settings About page now exposes a GitHub issue draft, environment copy,
bounded diagnostic ZIP export, documentation, releases, source and license links.
Shortcuts and framework acknowledgements remain available in a disclosure.

## Version authority

`backend/app/core/version.py` is the product version source. Vite reads it when
starting/building; the API imports it. The About panel and live status bar use
the injected version. Build identity includes the Git revision and a dirty
suffix when building a modified checkout. Restart Vite/rebuild after changing
version metadata. Frontend and backend versions are displayed separately.

## Export contract

- `GET /api/v1/support/diagnostics?minutes=15` is read-only, no-store, available
  in LIVE and LOCAL_OFFLINE, with a 1–60 minute range.
- UI offers 5, 15 and 60 minutes. Backend collection times out after 5 seconds;
  failure still produces a frontend-only archive and identifies the missing part.
- ZIP contains `diagnostics.json`; nothing is uploaded. The GitHub URL includes
  only the environment summary, never the archive or event list.
- Backend keeps at most 500 warning/error metadata records from shipped app
  code. Entries contain time, relative source location, severity and an
  allowlisted exception type. Messages, formatting args, exception text, locals,
  user/plugin source paths and arbitrary extras are never retained.
- Frontend keeps at most 300 events: uncaught errors/rejections and failures
  crossing the shared API request function. Only known error types, HTTP status
  and allowlisted API area names are retained; no URLs, bodies or stacks.
- Both windows are limited to the last hour. They cover the current page/process,
  not previous launches, worker processes, full console output or historical files.
  Empty event lists do not imply an error-free application. Buffers report their
  start time and number of events evicted by capacity.
- Frontend event/start timestamps use Unix milliseconds; backend uses Unix
  seconds. `generated_at` is ISO 8601 UTC.
- No chart/workspace contents, storage snapshots, account data, strategy source,
  plugin configuration, database files or raw health/debug snapshots are included.
- English support text is the fallback for locales without dedicated translations;
  Simplified Chinese, Traditional Chinese and English have dedicated copy.

## Validation (2026-09-21)

- Frontend support + shared API tests: 19 passed.
- Backend support + real offline-profile startup tests: 5 passed.
- Desktop support-link allowlist and window-manager tests: 7 passed. Only exact
  CandleScope GitHub support destinations open in the system browser, and only
  from a trusted application page; arbitrary external navigation remains blocked.
- TypeScript, targeted ESLint, i18n (30 locales), architecture check passed.
- Production build succeeds from the canonical Windows checkout path
  `E:/Disk0Merged/H/program/CandleScope/frontend`. The H: alias triggers an
  existing Vite HTML output-path error.
- In-app browser: environment copy succeeded; simulated clipboard rejection
  exposed the selectable manual-copy text; a real isolated offline backend
  returned version information; a stopped backend produced the partial-export
  message. Issue href inspected without opening/submitting a GitHub issue.
- Captured the actual Blob produced by each browser export via temporary test
  instrumentation, then independently checked ZIP CRC and decoded JSON using
  Python zipfile. Complete archive had backend version 0.3.0; partial archive
  had backend=null and a missing-backend explanation. Test overrides restored.
- In-app browser download notification timed out: browser-generated archive
  bytes are verified, but the browser's native Save/download completion and
  packaged desktop download UI are not verified.
- Screenshot and ZIP evidence: `output/support-qa/` (local, ignored).

The existing long-running backend must be restarted to register the new endpoint;
an older backend is treated as unavailable for diagnostics rather than breaking
frontend export.
