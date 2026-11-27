import assert from "node:assert/strict";
import test from "node:test";
import { EXCLUDED, RUN, inventory } from "./run-browser-suites.mjs";

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
