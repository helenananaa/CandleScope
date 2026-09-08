# PR #3 integration validation — 2026-09-08

## Integrated inputs

- PR head: `2ec2c720409f4322d5dddfa452f97438aa53f9b7`.
- Local main: `2c1082a5` (includes `47110e7b` strategy research workflows).
- Remote main baseline: `f6572c41bb056f525f8b5f56ea513429e647099f`.
- Integration uses a merge commit, preserving both histories.

## Conflict decisions

Resolved 15 conflicting files. Retained unified workspace navigation and training presets together with QA icons, responsive market summary, history preparation entry and form reset behavior. Preserved all added locale keys, preferring QA's user-facing replay terminology where text overlapped.

Result rendering retains raw values for signed styling/tooltips, formatted amounts/prices, missing-drawdown reasons, localized approximate-report labels and zero-trade win-rate handling. Shared semantic colors now cover both chart tester and standalone research results in light/dark themes. Keyboard shortcut hints are rendered as complete technical strings with the platform modifier.

Full testing found five Brazilian Portuguese messages rejected by the existing mixed-language check. Reworded those messages without changing the test. Added combined regression coverage for result rendering and preparation/preset coexistence.

## Validation

- Architecture and plugin architecture checks passed.
- i18n check passed: 9 locales, 4,245 keys; dedicated i18n tests 36/36 passed.
- Full ESLint and final TypeScript checks passed.
- Frontend full suite: 3,647 passed, zero failures/skips (final rerun).
- Merge-focused result/replay tests: 35 passed (overlaps the full suite).
- Desktop tests: 43 passed.
- Backend tests changed across both inputs: 86 passed.
- Production Vite build passed; existing large-chunk warnings remain.

Local command logs are retained under `output/pr3-integration/` in the integration worktree, not committed.

## Boundaries

This is source integration and automated regression validation. It does not repeat the prior Mac native-package GUI qualification or claim a new Windows native-package qualification. No production services were started, installed packages deployed, or user data migrated.
