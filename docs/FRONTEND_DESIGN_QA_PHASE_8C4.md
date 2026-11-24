# Frontend design refactor: Phase 8c4 QA (plugin surfaces on the kit)

- Date: 2026-11-23
- Branch: `design/phase-8c4-plugins`, on Phase 8c3b (`design/phase-8c3b-workspace`, PR #584)
- Plan: [`frontend/FRONTEND_DESIGN_REFACTOR_PLAN.md`](../frontend/FRONTEND_DESIGN_REFACTOR_PLAN.md), Phase 8 (part 8c4)
- **Intended visible change:** the plugin surfaces' buttons take the kit's look:
  - Destructive actions are the kit's danger button (red text and outline). Before, this was a red fill or nothing. They cover uninstall in the plugin center and, in the live control window, the global kill, live execution, revocation and their confirmations.
  - A surface's main action is primary: run command, save settings, and a view's command.
  - Dialog and panel close buttons show the kit's × icon.
  - The plugin center's tabs are kit tabs. Its chosen plugin and the palette's chosen command are tinted, without an accent outline.
  - The toolbar, the live control banner and the notice row keep their look.
  - Layout and behaviour stay.

## What changed

| Area | Change |
|---|---|
| Toolbar | The plugin commands, command palette, views, settings and live control are small `ControlButton`s. The live control button keeps its warning or danger tone. |
| Platform surfaces | Palette, settings and view close buttons → `IconButton`. The palette's commands → `row` `OptionButton`s, keeping the dialog's type, with the chosen one tinted. Run command and save settings → primary `Button`; a view's primary command → primary `Button`; save destination → `Button`. A dismissable notice → `row` `OptionButton` that keeps the notice strip's box, colours and hover. |
| Live control | The banner → `row` `OptionButton` that keeps its tone, stripes and square edges. In the window: close → `IconButton`; arm, disarm, audit download, preview, issue, receipt revoke and the other execution actions → `Button`; global kill, live execution, revoke authority and the confirmations' final steps → `danger` `Button`. |
| Plugin center | The plugin list → `row` `OptionButton`s, keeping the center's type. The current plugin is marked `aria-current` and is tinted. Detail: back → small ghost `Button`; the four pages → kit `Tabs`, with the page shown as their tab panel; enable → primary; disable, rollback, uninstall, settings and discover → `Button`; the uninstall or rollback confirmation → `danger`. |
| Management sections, native fields, sandbox frame | Permission grant, revoke and deny, paper kill switch, marketplace prepare, apply, activate and rollback, and trust change review and confirm → small `Button`s. Native fields' add and remove → small `Button`s. The sandbox frame's reload → small `Button`. |
| Kit | An `OptionButton` marked `aria-current` (`true` or `page`) shows as chosen, as one marked pressed or selected does. New kit test. |
| CSS | Removed the plugin stylesheets' own button rules: the generic `.plugin-toolbar`, `.plugin-action-row`, `.plugin-modal` and `.plugin-view-surface` button rules; the plugin center's generic button rules and its tab and list button rules; `.pc-danger`; `.live-danger-action`; the palette's `.active` command. Layout and content type stay. |
| Guardrails | Raw `<button>` ratchet 145 → 92. |

The plugin surfaces have no raw buttons left.

## Results

Before/after compare 8c3b (`d60627e8d`) with this branch, at 1440 × 900 in zh-CN (`output/design-8/plugin-shots-8c4.mjs`). The local service was not running, and the app skips the plugin runtime when offline. So every scene renders the plugin components with the same fixed fake runtime on both builds. The toolbar is placed in the real top bar. The fake runtime has three plugins, three palette commands (one with fields and a save destination), a settings form and a side panel view.

The scenes:
- the plugin center with the "more" menu open and the uninstall confirmation;
- the center's trust and permissions page;
- the command palette with a command chosen;
- the settings form;
- the side panel view, with the live control banner and a notice below it;
- the live control window;
- the global kill confirmation.

Dark throughout; light for four of them.

Found and fixed while capturing:
- The palette's commands and the plugin list dropped to the kit row's 13 px type; they keep their surface's type again.
- The live control banner took the kit's rounded corners; it is square again.

## Screens

Dark, 8c3b → this branch:

| | Before | After |
|---|---|---|
| Plugin center, uninstall confirmation | ![](assets/frontend-design-phase-8c4/center-dark--before.jpg) | ![](assets/frontend-design-phase-8c4/center-dark--after.jpg) |
| Trust and permissions | ![](assets/frontend-design-phase-8c4/center-permissions-dark--before.jpg) | ![](assets/frontend-design-phase-8c4/center-permissions-dark--after.jpg) |
| Command palette | ![](assets/frontend-design-phase-8c4/palette-dark--before.jpg) | ![](assets/frontend-design-phase-8c4/palette-dark--after.jpg) |
| Settings form | ![](assets/frontend-design-phase-8c4/settings-dark--before.jpg) | ![](assets/frontend-design-phase-8c4/settings-dark--after.jpg) |
| Toolbar, side panel view, banner and notice | ![](assets/frontend-design-phase-8c4/view-dark--before.jpg) | ![](assets/frontend-design-phase-8c4/view-dark--after.jpg) |
| Live control window | ![](assets/frontend-design-phase-8c4/live-dark--before.jpg) | ![](assets/frontend-design-phase-8c4/live-dark--after.jpg) |
| Global kill confirmation | ![](assets/frontend-design-phase-8c4/live-kill-dark--before.jpg) | ![](assets/frontend-design-phase-8c4/live-kill-dark--after.jpg) |

Light:

| | Before | After |
|---|---|---|
| Plugin center | ![](assets/frontend-design-phase-8c4/center-light--before.jpg) | ![](assets/frontend-design-phase-8c4/center-light--after.jpg) |
| Command palette | ![](assets/frontend-design-phase-8c4/palette-light--before.jpg) | ![](assets/frontend-design-phase-8c4/palette-light--after.jpg) |
| Toolbar, side panel view, banner and notice | ![](assets/frontend-design-phase-8c4/view-light--before.jpg) | ![](assets/frontend-design-phase-8c4/view-light--after.jpg) |
| Live control window | ![](assets/frontend-design-phase-8c4/live-light--before.jpg) | ![](assets/frontend-design-phase-8c4/live-light--after.jpg) |

## Verification

These are targeted local checks; CI runs the full check.

- `npm run check:styles` passes in strict mode, with raw `<button>` at 92, its ratchet.
- `npm run check:css-layers`, `npm run typecheck` (both tsconfigs) and ESLint on the plugin modules and the kit pass.
- `npm run build` passes. Its one warning is the size of the code editor's bundle, and 8c3b shows the same warning for the same bundle.
- 477 tests pass, covering:
  - plugins, extensions, components (the kit included);
  - the plugin center detail and refresh race scripts;
  - app, settings, i18n;
  - every test that reads the app's stylesheets;
  - style metrics.
- No existing test needed changing. One new kit test covers `aria-current` on an option.
- The smoke, package and validation scripts select no plugin button markup. The plugin tests' hooks (`data-live-control-banner`, `data-live-global-kill`, `data-plugin-command…`, `data-preview-live-confirmation`) stay on the buttons.

## Known gaps

- **Not run locally: the full `npm run check`.** GitHub CI runs it on the PR.
- **Seen only rendered by the components with a fake runtime**, not with real plugins installed: the local service was not running. Installing, enabling, running a command, saving settings and the live control flows were not exercised by hand. The plugin tests cover the components.
- **The global kill and the other live-control danger actions lose their red fill.** They are the kit's danger button, red text and outline, like every other destructive action now.
- **The plugin center's detail tabs now move with the arrow keys as kit tabs** (roving focus). Before, each tab took its own Tab stop.
- **Not seen:** the sandbox frame's reload, the marketplace and trust-change actions, and the paper kill switch. They need a sandbox view, marketplace data or a paper broker. They use the same small `Button` as the permission actions that were seen.
