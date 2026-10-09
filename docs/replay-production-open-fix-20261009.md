# Replay training opening fixes — 2026-10-09

Creating or reopening a prepared training could fail at several boundaries:

- A saved uncertain submission reused a completed preparation receipt after its
  training run had been deleted, then navigated to `TRAINING_RUN_NOT_FOUND`.
- Preparing a slice of existing immutable history tried to publish that slice
  over a larger archive object, failing the archive's overlap check.
- Finite prepared BAR windows could bind to unrelated later archive islands or
  require native display archives that preparation had never acquired.
- Returning to the hub immediately after opening could encounter a transient
  adapter lease and leave the user on the training page.

Preparation now verifies the live run before navigation. Only an explicit
not-found result rotates the saved submission key and permits one fresh
submission; uncertain network failures keep the original key. Existing archive
rows are verified and reused without republishing overlapping objects.

Prepared BAR selections retain their requested terminal boundary through
recovery, and display queries aggregate their pinned base history. The hub
workflow retries only the explicit transient revision-conflict response for up
to 20 attempts, 250 ms apart, and still requires a durable checkpoint and release
before navigation. Persistence failures are not retried.

## Validation

The repaired local production package was exercised twice with isolated profiles
and synthetic historical data, using its bundled backend. Each pass covered
creation, chart opening, deletion, recovery from the old saved submission key,
advancement, reload, hub reopening, full application restart, and switching the
chart to 4h. Both had visible candles and no page exceptions. The acceptance
runner is `frontend/scripts/replay-desktop-open-smoke.mjs`; it retains JSON
receipts and screenshots, including failure receipts.

The package's app.asar SHA256 was
`c42d2715e5c57699335e152791a2ee89639670c3b74c7840858c9b2b798bb000`.
These package checks precede integration with the latest remote UI changes; they
are scoped replay-opening evidence, not comprehensive trading/network coverage.

After applying only this repair to remote main `29f164e3`, 426 replay tests and
115 related preparation/replay backend tests passed. TypeScript, scoped ESLint,
the production build and diff whitespace checks also passed on the integration.
Other local feature commits and user-profile data are excluded from this change.
