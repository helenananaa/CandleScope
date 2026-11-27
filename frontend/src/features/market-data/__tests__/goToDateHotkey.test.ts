import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { isGoToDateShortcut } from "../useGoToDateHotkey.js";

const press = (changes: Partial<Parameters<typeof isGoToDateShortcut>[0]> = {}) => isGoToDateShortcut({
  defaultPrevented: false, repeat: false, isComposing: false, altKey: true, ctrlKey: false, metaKey: false,
  shiftKey: false, code: "KeyG", target: null, ...changes,
});

test("Alt+G alone opens Go to date", () => {
  assert.equal(press(), true);
  for (const changes of [{ altKey: false }, { ctrlKey: true }, { metaKey: true }, { shiftKey: true }, { repeat: true },
    { isComposing: true }, { defaultPrevented: true }, { code: "KeyH" }]) assert.equal(press(changes), false, JSON.stringify(changes));
});

test("chart cells, replay training and both replays share the shortcut (PL-6)", () => {
  const hook = readFileSync(new URL("../useChartTimeNavigation.ts", import.meta.url), "utf8");
  assert.match(hook, /useGoToDateHotkey\(active && enabled && !!seek, /);
  const quick = readFileSync(new URL("../../trading-accounts/QuickReplayOverlay.tsx", import.meta.url), "utf8");
  assert.match(quick, /useGoToDateHotkey\(active && canNavigate, /);
  // Quick replay moves its own cursor through the same seek and cut as stepping.
  assert.match(quick, /quickReplayCursorAt\(timeMs, \{ stepSec, minCursor, maxCursor \}\)/);
  assert.match(quick, /setPlaying\(0\);\s*seek\(placed\.cursor\);/);
  // And says so: it is the replay that moves, not the view.
  assert.match(quick, /hint=\{t\("chartTime\.replayCursorHint"\)\}/);
  const result = readFileSync(new URL("../../strategy-research/StrategyResultReplay.tsx", import.meta.url), "utf8");
  assert.match(result, /hint=\{t\("chartTime\.replayCursorHint"\)\}/);
});
