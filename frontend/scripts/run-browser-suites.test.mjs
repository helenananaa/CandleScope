import assert from "node:assert/strict";
import test from "node:test";
import fs from "node:fs";
import { BACKENDS, EXCLUDED, GROUPS, RUN, inventory } from "./run-browser-suites.mjs";

test("every browser suite runs in CI or is excluded with a reason", () => {
  const found = inventory();
  assert.deepEqual(found.problems, []);
  assert.equal(found.run.length + found.excluded.length, found.suites.length);
  for (const { reasons } of found.excluded) assert.ok(reasons.length && reasons.every((reason) => reason.length > 40), reasons.join("; "));
});

test("the replay, quick replay and account suites named in the post-launch backlog run", () => {
  const { run } = inventory();
  for (const suite of [
    "src/features/replay/__tests__/replayOperations.browser.tsx",
    "src/test/quickReplayStep.browser.tsx",
    "src/features/trading-accounts/chartAccountOverlays.browser.tsx",
    "src/features/trading-accounts/practiceOrderTicket.browser.tsx",
  ]) assert.ok(run.includes(suite), `${suite} does not run`);
  const replayAdapters = inventory().suites.filter((suite) => /^src\/chart-adapter\/__tests__\/replay/.test(suite));
  assert.ok(replayAdapters.length >= 6);
  for (const suite of replayAdapters) assert.ok(run.includes(suite), `${suite} does not run`);
});

test("a fixture is run or excluded, never both", () => {
  const fixtures = RUN.map((item) => item.fixture);
  assert.equal(new Set(fixtures).size, fixtures.length);
  for (const fixture of fixtures) assert.ok(!Object.hasOwn(EXCLUDED, fixture), fixture);
});

test("the Python-backed suites run in the python group against a maintained backend/tests server", () => {
  const { imports, run } = inventory();
  const python = RUN.filter(GROUPS.python);
  for (const suite of [
    "src/features/replay/__tests__/replayNotes.browser.tsx",
    "src/chart-adapter/__tests__/backendSynthetic.browser.tsx",
    "src/chart-adapter/__tests__/pinnedSynthetic.browser.tsx",
    "src/chart-adapter/__tests__/chartIndicatorInput.browser.tsx",
    "src/chart-adapter/__tests__/chartCalculation.browser.tsx",
    "src/chart-adapter/__tests__/chartMarketCalculation.browser.tsx",
  ]) {
    assert.ok(run.includes(suite), `${suite} does not run`);
    assert.ok(python.some((item) => imports.get(item.fixture).includes(suite)), `${suite} is not in the python group`);
  }
  for (const item of python) {
    const { source } = BACKENDS[item.backend];
    // QA evidence under docs/qa stays frozen; CI runs only maintained fixtures.
    assert.match(source, /^tests\/[a-z_]+_browser_server\.py$/);
    assert.ok(fs.existsSync(new URL(`../../backend/${source}`, import.meta.url)), source);
  }
});

test("each fixture runs in exactly one of the browser and python groups", () => {
  for (const item of RUN) assert.equal(GROUPS.browser(item) + GROUPS.python(item), 1, item.fixture);
  assert.equal(RUN.filter(GROUPS.all).length, RUN.length);
});
