# Frontend design refactor: Phase 5f5 QA (replay right rail: notes, watchlist, market data)

- Date: 2026-11-14
- Branch: `design/phase-5f5-replay-rail`, based on `design/phase-5f4-replay-review` (PR #412)
- Plan: [`frontend/FRONTEND_DESIGN_REFACTOR_PLAN.md`](../frontend/FRONTEND_DESIGN_REFACTOR_PLAN.md) §2.4, §2.5, §2.6 and the Phase 5 rows. Contract: [`DESIGN.md`](../DESIGN.md#rail-views)
- **Intended visible change:** the replay right rail's 回放笔记, 自选 and 市场 views, and the rail shown during a read-only review, use kit controls on tokens. What they show and do is unchanged.

The right rail was split again when this phase started: **5f5** the notes, watchlist, market data view and review rail (this note); **5f6** the order ticket (下单) and the account view (仓位). Those two are about 1,850 lines of one component, and the tests check much of their source and styles.

## What changed

| Area | Change |
|---|---|
| 回放笔记: list | Each note is a row: a 原始记录 or 复盘补记 badge with the market time, the text, linked trades and screenshots, then the saved time with 编辑 and 版本历史 as quiet buttons. Before, each note had a body-size heading, a two-row table of times and bordered browser buttons. 新增笔记 is the view's primary button; an empty moment is an `EmptyState`; load, draft and save failures are alerts. |
| 回放笔记: editor | The text is a kit field (计划或复盘内容) with its hint linked to it, instead of a large label and a separate paragraph. The trade/fill picker and the screenshot controls are sections with kit buttons, their hints in small text, and kit checkboxes in their lists. A pending screenshot is a warning alert with 重试截图提交 and 取消待提交截图. 保存 is primary; 关闭 is quiet. |
| Version history, screenshots | Versions are rows on a quiet surface; the screenshot viewer has a title, its times on one line, an icon close button, and the dialog shadow and backdrop tokens. |
| Rail subtitle | The notes view's subtitle repeated its title (回放笔记 · 回放笔记); it is now 计划与复盘. |
| 自选 | Kit search field. Search results are rows (symbol, then 已添加 / 加入自选 / 不可用) with 当前活动图表 and 在新图表打开 under them, instead of a three-column strip that truncated the symbol to "B.. U.. S..". A watchlist row shows the symbol, venue and price; the open market has an accent edge; 在新图表打开 is an icon button. Errors are alerts. |
| 市场 | Kit tabs and tab panel (arrow keys move between 盘口, 订单流, 指标). 未启用历史盘口 and 当前来源不支持订单流 are empty states instead of amber boxes, since the source simply has no such data; a cleared book or broken trade flow is a warning alert with 重新校验并同步. Book levels are two aligned columns; trade flow figures are kit stats and the tape a list. |
| Review rail | Shown during 只读复盘: the "复核 · 只读" eyebrow is a badge next to the symbol, the eight facts are one list, the incomplete-account notices are alerts, and the notes sit under them as a kit disclosure. |
| Styles | About 120 rules for these views in `replay.css`, `replayPanels.css`, `trainingHub.css`, `lateFixes.css` and `marketRail.css` are replaced by 95 token-based rules at the end of `replay.css`. Among the removed: element rules that restyled every button in the notes panel and in the watchlist's search and rows. |
| Copy | One new string in all 30 languages (计划与复盘). |

## Screens

The base build (Phase 5f4, `ffdbe566d`) and this branch, 1440 px, `zh-CN` unless marked, on one of the local runs. Replay writes (orders, notes, screenshots, adding markets) were refused in every capture. The local run has no notes, so the "two notes" captures add two sample notes to the real notes response in the page.

| | Before | After |
|---|---|---|
| 回放笔记 with two notes | ![](assets/frontend-design-phase-5f5/notes-sample--before--dark.jpg) | ![](assets/frontend-design-phase-5f5/notes-sample--after--dark.jpg) |
| 回放笔记 with two notes (light) | ![](assets/frontend-design-phase-5f5/notes-sample--before--light.jpg) | ![](assets/frontend-design-phase-5f5/notes-sample--after--light.jpg) |
| 回放笔记 with two notes, English | ![](assets/frontend-design-phase-5f5/notes-en-sample--before--dark.jpg) | ![](assets/frontend-design-phase-5f5/notes-en-sample--after--dark.jpg) |
| 回放笔记, empty | ![](assets/frontend-design-phase-5f5/notes--before--dark.jpg) | ![](assets/frontend-design-phase-5f5/notes--after--dark.jpg) |
| New note | ![](assets/frontend-design-phase-5f5/noteseditor--before--dark.jpg) | ![](assets/frontend-design-phase-5f5/noteseditor--after--dark.jpg) |
| 自选 | ![](assets/frontend-design-phase-5f5/watchlist--before--dark.jpg) | ![](assets/frontend-design-phase-5f5/watchlist--after--dark.jpg) |
| 自选 (light) | ![](assets/frontend-design-phase-5f5/watchlist--before--light.jpg) | ![](assets/frontend-design-phase-5f5/watchlist--after--light.jpg) |
| 自选, English | ![](assets/frontend-design-phase-5f5/watchlist-en--before--dark.jpg) | ![](assets/frontend-design-phase-5f5/watchlist-en--after--dark.jpg) |
| 自选, searching "USDT" | ![](assets/frontend-design-phase-5f5/watchsearch--before--dark.jpg) | ![](assets/frontend-design-phase-5f5/watchsearch--after--dark.jpg) |
| 市场 · 盘口 | ![](assets/frontend-design-phase-5f5/market--before--dark.jpg) | ![](assets/frontend-design-phase-5f5/market--after--dark.jpg) |
| 市场 · 盘口 (light) | ![](assets/frontend-design-phase-5f5/market--before--light.jpg) | ![](assets/frontend-design-phase-5f5/market--after--light.jpg) |
| 市场, English | ![](assets/frontend-design-phase-5f5/market-en--before--dark.jpg) | ![](assets/frontend-design-phase-5f5/market-en--after--dark.jpg) |
| 市场 · 订单流 | ![](assets/frontend-design-phase-5f5/marketflow--before--dark.jpg) | ![](assets/frontend-design-phase-5f5/marketflow--after--dark.jpg) |
| 市场 · 指标 | ![](assets/frontend-design-phase-5f5/marketind--before--dark.jpg) | ![](assets/frontend-design-phase-5f5/marketind--after--dark.jpg) |

## Verification

**In the running app** (headless, 1440 px, replay writes refused):
- 新增笔记 opened the editor; its text field is labelled and described by its hint. 选择成交 opened the record list (此事件尚无可关联记录。) and 选择已保存截图 the screenshot list (当前视图没有可关联的已保存截图。); 关闭 closed the editor.
- 市场: the tab panel is labelled by the selected tab; ArrowRight moved from 盘口 to 订单流 and showed its panel.
- 自选: searching "USDT" listed the run's market as 已添加 with its two open actions.
- Not run, because they change the run: saving a note, capturing a screenshot, adding a market, opening a market in a chart, re-syncing the book. The review rail (shown only during a review, which is a write) was checked through its render test, not in the app.

**Unit and source tests:** the replay and replay-launcher tests pass (685), including the review rail's render tests (`<dd>--</dd>` for unavailable values) and the watchlist, trade-flow and rail source checks.

**Scripts:** the hooks `replay-soak.mjs` uses in the watchlist are kept: the search field's label, `.replay-market-search-results button` with the symbol in `<strong>`, `.replay-watchlist-row[.active]` with `data-replay-track-id`, `button.replay-watchlist-market`, and the collapsed pane's `.wl-collapse-btn`. The notes browser check (`replayNotes.browser.tsx`, run by hand against a fixture backend) finds buttons by their text, the field as `textarea`, pickers by `input[type="checkbox"]` and the screenshot viewer as a native `dialog` whose first button closes it; all are kept. Neither was run.

**Style metrics** (against 5f4): class names with no CSS rule 0 (unchanged), raw `<button>` 602 → 571, `<Button>` uses 181 → 208.

**Full check:** `npm run check` passes: 5,164 frontend tests, 137 desktop tests, lint (one existing warning), both typechecks and the build.

## Known gaps

- **Copy (Phase 6):** the market view names internal modes (`TOUCH_OR_TAPE_V2`, "Hosted、range 与 security 指标", "agg #"); the screenshot hint lists byte and pixel limits; the watchlist's group comes from the launch snapshot and can read "Watchlist" in English.
- **Two raw buttons stay in the watchlist** (the market row and the search result's add button): they are list rows rather than buttons in a toolbar, and the soak script selects them.
- **The screenshot viewer stays a native `<dialog>`**, outside the overlay stack, because the notes browser check reads it as one.
- **Still to come:** the order ticket and the account view (5f6).
- **Desktop app:** not tested.
