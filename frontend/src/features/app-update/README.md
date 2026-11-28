# App update check

The desktop app asks GitHub whether a newer CandleScope release exists and, if so,
shows a quiet notice that links to that release's page. It never downloads or
installs anything. The browser build skips the check: it is always current.

- `releaseModel.ts`: pure rules. App releases are published, non-draft,
  non-prerelease releases tagged exactly `vMAJOR.MINOR.PATCH`; plugin releases in
  the same repository (`candlescope-plugin-pine-compat-v0.3.3`) and release
  candidates are ignored. Versions compare by semver against `APP_VERSION`. The
  release page link is built from the version, never read from the response.
- `updateCheckService.ts`: one unauthenticated `GET /repos/…/releases` through the
  page's own network stack (system proxy, normal certificate checks). Any failure
  throws.
- `updateCheckScheduler.ts`: checks at startup, then at most once every 24 hours,
  only while "Check for updates" is on. Failures (network, rate limit, bad JSON,
  an intercepted certificate) are logged to the console and never shown.
- `updateCheckPreferences.ts`: the setting and the skipped versions, in this
  profile's browser storage (`candlescope-update-check`).
- `useAppUpdateCheck.ts`: the React wiring. `App.tsx` runs the check in the
  desktop main window only; `AboutSettingsPanel` shows the switch on desktop.

"View release" opens the page through the desktop shell's external-link allowlist
(`desktop/support-links.mjs`), which accepts `…/releases/tag/vX.Y.Z` pages only.
"Skip this version" is remembered per version. Closing the notice hides that
version until the next launch.
