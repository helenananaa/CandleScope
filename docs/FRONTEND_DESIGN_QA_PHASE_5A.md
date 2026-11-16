# Frontend design refactor: Phase 5a QA (the Settings frame)

- Date: 2026-11-14
- Branch: `design/phase-5a-settings`, based on `design/phase-4c-chart-appearance` (PR #388)
- Plan: [`frontend/FRONTEND_DESIGN_REFACTOR_PLAN.md`](../frontend/FRONTEND_DESIGN_REFACTOR_PLAN.md) §2.2, §2.5, §2.8 and the Phase 5 row. Contract: [`DESIGN.md`](../DESIGN.md#settings)
- **Intended visible change:** Settings is one larger dialog that keeps its frame for every category, including 插件与扩展 (the Plugin Center). 保存并关闭 is gone; the proxy says when it has unsaved edits and asks before they are lost. 数据管理 and AI MCP are rebuilt from the kit.

Phase 5 lands surface by surface; the split is in the plan. 5a covers the Settings frame and the categories that needed it; 交易所, 存储与维护, 高级维护 and 关于与支持 follow in 5b.

## What changed

| Area | Change |
|---|---|
| Frame | One dialog, up to 1080 × 760 (was 960 × 680), so the Plugin Center fits inside it. The close button is the kit `IconButton`. The sidebar no longer has 保存并关闭: changes already applied as they were made, so the button only closed the dialog and suggested a save that did not happen. |
| Plugin Center | Opens inside Settings as the 插件与扩展 category. Before, it replaced Settings with a differently designed window with its own header, 返回 link, 关闭 button, tab style and native select. Its sections (我的插件, 发现插件, 高级管理, 可信扩展) are kit `Tabs` with 刷新 and 安装插件 beside them; search and the status filter are kit `Input` and `Select`; its messages are `InlineAlert`s and its status pills are `Badge`s. While a plugin installs, Settings cannot be closed and the other categories are disabled, as the old window refused Escape; Escape on the install page still steps back to 我的插件 first. (Installing needs the desktop app's management connection, so these two were not exercised here.) |
| Plugin detail | The 概览 tab no longer repeats its own name as a heading or restates the status the badge shows ("需处理" appeared three times). |
| Proxy (网络连接) | The one form that needs an explicit save. 保存代理 is enabled only with unsaved edits, which a note beside it and a dot on 网络连接 announce. Closing Settings with unsaved edits asks 放弃未保存的网络设置？ (取消 is focused; Escape cancels). Fields are kit `Field`/`Input`/`Select`/`Checkbox`; each route's live diagnostics (connections, flow, failures) sit in a 运行状态 disclosure; test and save results are `InlineAlert`s. "检测到系统代理" and "当前生效" lost their trailing colons in all 30 languages. |
| 数据管理 | Kit `Tabs` replace three bordered buttons with `aria-pressed`. The library section is two rows, each a title, one line of description and its button: 本地资料库 (new description) and 数据工作台 with a 只读 badge. The workbench text is distilled: "SQLite", "VACUUM" and "真实数据" are gone. |
| AI MCP | Its own icon (it shared the network globe). In a browser it is an empty state saying it is in the desktop app. The desktop panel, plain markup until now (the last unstyled class name), is rebuilt: a status badge, kit checkboxes and buttons, a 连接 section with the address, a configuration `Textarea`, and lists for open charts and recent calls. |
| Kit | `.ui-input:disabled` sets only the background colour, so a disabled `Select` keeps its chevron (the shorthand cleared it in the extension manager's locked form). New `.ui-visually-hidden` for text only assistive technology reads. |
| Stylesheet | The Settings CSS moved from a 2,364-line `<style>` string (`SettingsModalStyles.tsx`), re-injected each time Settings opened, into `features/settings/settings.css`, imported last in the features layer where the string used to apply. The one unscoped rule in it, `input[type="color"]`, only applied while Settings was open; it is now scoped to the Settings panel so it does not restyle colour inputs elsewhere. |
| Copy | 11 strings in all 30 languages (the unsaved prompt, the library rows, 运行状态, the AI connection labels). `settings.workbench.desc` and `settings.workbench.badge` are gone. |

## Screens

The base build (Phase 4c, `d38406ce9`) and this branch, 1440 px, `zh-CN` unless marked.

| | Before | After |
|---|---|---|
| 外观显示 (the frame) | ![](assets/frontend-design-phase-5a/appearance--before--dark.jpg) | ![](assets/frontend-design-phase-5a/appearance--after--dark.jpg) |
| 插件与扩展: before, a separate window | ![](assets/frontend-design-phase-5a/plugins--before--dark.jpg) | ![](assets/frontend-design-phase-5a/plugins--after--dark.jpg) |
| 插件与扩展 (light) | ![](assets/frontend-design-phase-5a/plugins--before--light.jpg) | ![](assets/frontend-design-phase-5a/plugins--after--light.jpg) |
| 插件与扩展, English | ![](assets/frontend-design-phase-5a/plugins-en--before--dark.jpg) | ![](assets/frontend-design-phase-5a/plugins-en--after--dark.jpg) |
| 插件与扩展 → 可信扩展 | ![](assets/frontend-design-phase-5a/extensions--before--dark.jpg) | ![](assets/frontend-design-phase-5a/extensions--after--dark.jpg) |
| 网络连接 | ![](assets/frontend-design-phase-5a/network--before--dark.jpg) | ![](assets/frontend-design-phase-5a/network--after--dark.jpg) |
| 网络连接 (light) | ![](assets/frontend-design-phase-5a/network--before--light.jpg) | ![](assets/frontend-design-phase-5a/network--after--light.jpg) |
| Closing with unsaved proxy edits (after only) | | ![](assets/frontend-design-phase-5a/unsaved-proxy--after--dark.jpg) |
| 数据管理 | ![](assets/frontend-design-phase-5a/data--before--dark.jpg) | ![](assets/frontend-design-phase-5a/data--after--dark.jpg) |
| 数据管理 (light) | ![](assets/frontend-design-phase-5a/data--before--light.jpg) | ![](assets/frontend-design-phase-5a/data--after--light.jpg) |
| AI MCP in a browser | ![](assets/frontend-design-phase-5a/ai--before--dark.jpg) | ![](assets/frontend-design-phase-5a/ai--after--dark.jpg) |
| AI MCP, desktop panel (rendered with a stubbed desktop bridge) | ![](assets/frontend-design-phase-5a/ai-desktop--before--dark.jpg) | ![](assets/frontend-design-phase-5a/ai-desktop--after--dark.jpg) |
| 关于与支持 (the frame) | ![](assets/frontend-design-phase-5a/about--before--dark.jpg) | ![](assets/frontend-design-phase-5a/about--after--dark.jpg) |

## Verification

**In the running app** (browser pane, 1440 px):
- 网络连接 → 自定义: 保存代理 became enabled, "有未保存的更改" appeared beside it and a dot on 网络连接. Escape opened the prompt with 取消 focused; Escape again closed only the prompt and Settings stayed open. 放弃更改 closed Settings; reopening showed the saved mode (系统代理) and no dot.
- 插件与扩展 opened inside the dialog with 我的插件 selected; 可信扩展 showed the extension manager, its locked selects now with their chevron.
- 数据管理, AI MCP and 关于与支持 in both themes; 插件与扩展 in English.
- The replay hub's appearance-only Settings (`PageSettingsDialog`) opens with the same frame and kit close button.

**Stylesheet move:** `npm run css:cascade -- --base HEAD`, run right after the move: the only declarations added or removed are the colour rule's six, now scoped; 793 reported winner changes, all against rules scoped to other features' roots (`.strategy-research-shell …`, `.native-strategy-panel …`, `.local-analysis-anchor …`) that load lazily after the global stylesheet. None can apply: Settings renders in the overlay host, outside every page root.

**Unit tests:**
- `ProxySettingsPanel.test.tsx`: 保存代理 is enabled only with unsaved edits, which are announced; the address is a labelled kit field; route diagnostics sit behind a disclosure.
- `settingsPureKernels.test.ts`: unsaved proxy edits are detected (mode, address, strategy, routes; surrounding spaces ignored; nothing before the settings load); every category has its own icon.
- The plugin center's existing static tests (`PluginV1Compatibility.test.tsx`) pass against the inline version.

**Style metrics** (against 4c): class names with no CSS rule 1 → 0 (target met), raw `<button>` 752 → 741, inline styles 166 → 162.

**Full check:** `npm run check` passes: 5,142 frontend tests, 137 desktop tests, lint (one existing warning), both typechecks and the build.

## Known gaps

- **Desktop app not run.** The extensions smoke (`scripts/trusted-extensions-desktop-smoke.mjs`) now finds the plugin center's sections as tabs; it was only syntax-checked. The AI MCP panel was checked with a stubbed bridge, not a real desktop session.
- **Inside the Plugin Center**, the plugin list, detail tabs, marketplace and advanced sections keep their own buttons and cards; they are rebuilt with the extension manager's leftovers in 5i.
- **交易所, 存储与维护, 高级维护 and 关于与支持** are unchanged apart from the frame; they are 5b.
- **Data workbench** still opens as its own window from 数据管理; it is rebuilt in 5h.
