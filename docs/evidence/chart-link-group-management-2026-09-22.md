# Chart link group management

Implemented chart-header group selection (including independent charts and create-and-join), a grouped member editor at the top of the linking panel, and retention of the panel tab across close/reopen within the running app.

The member editor lists mounted layout cells across workspace windows with symbol, interval, exchange, market type, and window/chart position. Users can select individual rows, an entire group, or all charts, then move them into an existing group, detach them, or create a group and join it. Each bulk action updates the document once and uses existing membership synchronization policies. Invalid bulk destinations are ignored; unknown and duplicate cell IDs are handled safely.

## Validation

- 104 chart-workspace tests passed, including new bulk synchronization and detach/invalid-target cases.
- Typecheck, targeted ESLint, architecture check, i18n check (30 locales), and diff whitespace check passed.
- Production build passed from `E:/Disk0Merged/H/program/CandleScope/frontend`. Running it through the mapped H: path failed in Vite HTML asset emission because physical and mapped drive paths differed. No build configuration was changed.
- Playwright against the actual application: created a four-chart workspace; selected two members and created/joined a group; closed and reopened the panel and verified the linking tab stayed selected; bulk detached the two members; used a chart-header selector to create/join, switch group, and detach; bulk joined an existing group; refreshed and verified the two selected memberships persisted.
- Visually inspected the member editor at 1280×720. Screenshot: `output/playwright/chart-link-members-1280.png` (local, ignored artifact).

## Limits

The backend was not running during browser verification, so existing API/WebSocket connection errors and the plugin-unavailable banner were present. This run validates frontend interaction and local workspace persistence, not live market-data synchronization or native multi-window propagation. Group policy behavior is covered by the workspace tests.

No commit or push performed.
