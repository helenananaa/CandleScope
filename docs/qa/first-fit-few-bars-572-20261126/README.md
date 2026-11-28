# First fit on a few bars (#572, 1.0.1)

Captures from the browser check `frontend/src/test/chartFirstFit.browser.tsx`, run with

    node scripts/frontend-script-integration.mjs --chart-first-fit --capture --out <dir>

from `frontend/` (real Chromium, production-minified fixture, actual `SingleChartPanes`, chart canvas,
live window store and visible-range storage; synthetic commits, not a packaged-app run). The chart is
800 x 400 px; prices have 8 decimals because the fixture has no symbol precision.

- `before-first-launch.png`: main `f02fc17c6`. Fresh profile; the first ready window held 4 bars, then
  500 bars arrived. The view stays on the 4-bar fit (78 px a bar) and that spacing is saved.
- `before-reopen-1.0.0-profile.png`: main `f02fc17c6`. A profile that saved the 4-bar fit reopens with
  500 bars and restores the zoom.
- `after.png`: this branch, both cases. The view fits the 500-bar window (about 1.4 px a bar).
