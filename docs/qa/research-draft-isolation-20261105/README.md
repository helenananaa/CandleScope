# Independent chart-to-research drafts

Product source: `80815bf9d7e2abce6af35610f67852c562422a05`, above #259. This addresses a real shared-draft defect in the existing #158 entry, not completion of #157/#158/#165.

The original handoff copied a mutable draft ID. Both chart and research editors subscribed/autosaved to the same DraftStore entry. Two real Store counterexamples (Pine/Python) changed the research program, then observed the originating chart source and revision overwritten. `isolation-before-writes.log.gz` preserves those failures.

The chart now saves the clicked editor state and passes that exact saved record to the handoff. The handoff copies code/language/cursor into a new persisted experiment draft, snapshots parameters/range/execution settings before awaiting I/O, and records the originating draft ID/revision. Navigation follows successful experiment and handoff persistence. Menu and control entry use the same save/ownership path; concurrent entry clicks share the in-flight operation. Existing chart/continuous accounts are not controlled or copied by this path. Old versionless handoffs that alias a draft are refused while their original bytes remain; reopen from the chart to create an isolated experiment.

## Checks

- Full frontend check (`frontend-check-verified.log.gz`) exited 0: **4918 regular tests, 1 isolated performance test, 130 desktop tests**, frontend/plugin contracts, 30 locales/5498 keys, types, lint and production build. The existing SingleChartPanes hook warning and build size warnings remain. Subsequent fixture-only layout/stylesheet adjustments do not change production source or build; the final browser run verifies them directly.
- Four new tests cover both languages' actual original-source preservation after research saves, persistence through a fresh Store, clicked code/nested settings captured across an intentionally held write, failed persistence publishing no handoff, and preserving/refusing the old alias record. Existing exact chart/conditions/offline-boundary handoff checks now require the independent draft. Counts overlap the full suite.
- `browser-qualified-receipt.json.gz` records **four actual browser flows**: Pine/Python × menu/control entry. The unchanged production chart and research components, registry, DraftStore, handoff and real Monaco inputs run in a test-only two-editor container. Source is changed before handoff; research code is typed through the real editor, flushed, and both independent records are verified after reload. There are zero JS page errors and zero API mutations. Before editing research, the chart's existing initial-cursor 550ms autosave is drained so its unrelated cursor metadata is not confused with a source rewrite. The final 1440px screenshots were inspected and show the distinct programs.

## Earlier failures retained

The first focused command ran from the wrong working directory and matched no tests. The first full check found an unsafe JSON assignment, corrected by validating from unknown; subsequent runs identified the missing fixture tsconfig entry and required component export. Browser attempts first lacked a cached headless-shell executable (the final driver reuses installed Chrome), then encountered Vite dependency-optimization reload, the current Monaco contenteditable control rather than a textarea, and unrelated initial-cursor autosave. Earlier fixture screenshots also had a collapsed editor; the final fixture supplies an explicit editor flex/height container and requires visible independent code before capture. None of those failed runs counts as acceptance.

## Limits

This proves draft/settings isolation and the actual two-editor browser flow. It is not a native packaged chart-to-workbench/full quit/restart result, strategy execution/financial acceptance, research result comparison, or explicit selected-version return to original/specified chart. Those original requirements remain open, including independent Windows evidence. The separate #200 public Native retry gate is unchanged. Final-head/base CI gates main merge; development continues without waiting.
