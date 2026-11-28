import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import {
  replayDateNavigationEnabled,
  replayPublicTimePolicy,
  replayViewNavigationMode,
} from "../replayPublicTimeModel.js";
import { REPLAY_V2_ENUMS } from "../replayV2Types.js";

const ready = { active: true, reviewing: false, loading: false } as const;
const hiddenPolicies = REPLAY_V2_ENUMS.time_disclosure_policy.filter(policy => policy !== "NONE");

test("Go-to-date is offered only when the session discloses absolute time", () => {
  assert.ok(hiddenPolicies.length > 0);
  assert.ok(hiddenPolicies.every(policy => policy.startsWith("HIDE_")));
  assert.equal(replayDateNavigationEnabled({ ...ready, publicTimePolicy: "NONE" }), true);
  for (const publicTimePolicy of hiddenPolicies) {
    assert.equal(
      replayDateNavigationEnabled({ ...ready, publicTimePolicy }),
      false,
      `${publicTimePolicy} must disable the Go-to-date dialog and Alt+G`,
    );
  }
});

test("Go-to-date stays off while inactive, in review or loading, even with absolute time", () => {
  for (const state of [
    { ...ready, active: false },
    { ...ready, reviewing: true },
    { ...ready, loading: true },
  ]) {
    assert.equal(replayDateNavigationEnabled({ ...state, publicTimePolicy: "NONE" }), false);
  }
});

test("the page policy fails closed until the server says otherwise", () => {
  assert.equal(replayPublicTimePolicy(undefined, undefined), "HIDE_ALL");
  assert.equal(replayPublicTimePolicy(null, null), "HIDE_ALL");
  assert.equal(replayPublicTimePolicy(undefined, true), "HIDE_ALL");
  assert.equal(replayPublicTimePolicy(undefined, false), "NONE");
  for (const policy of REPLAY_V2_ENUMS.time_disclosure_policy) {
    assert.equal(replayPublicTimePolicy(policy, false), policy);
    assert.equal(replayPublicTimePolicy(policy, true), policy);
  }
});

test("hidden dates get relative view moves instead of Go to date (PL-8)", () => {
  assert.equal(replayViewNavigationMode({ ...ready, publicTimePolicy: "NONE" }), "dates");
  for (const publicTimePolicy of hiddenPolicies) {
    assert.equal(replayViewNavigationMode({ ...ready, publicTimePolicy }), "relative", publicTimePolicy);
  }
  for (const state of [{ ...ready, active: false }, { ...ready, reviewing: true }, { ...ready, loading: true }]) {
    for (const publicTimePolicy of REPLAY_V2_ENUMS.time_disclosure_policy) {
      assert.equal(replayViewNavigationMode({ ...state, publicTimePolicy }), null);
    }
  }
});

test("the training page feeds view navigation through the guard", () => {
  const shell = readFileSync(
    resolve(dirname(fileURLToPath(import.meta.url)), "../ReplayTrainingPageShell.tsx"),
    "utf8",
  );
  const call = /useChartTimeNavigation\(\{([\s\S]*?)\}\);/.exec(shell);
  assert.ok(call, "ReplayTrainingPageShell must call useChartTimeNavigation");
  assert.match(shell, /const viewNavigation = replayViewNavigationMode\(\{/);
  assert.match(call[1]!, /enabled:\s*viewNavigation !== null/);
  // Relative moves never pass the revealed boundary.
  assert.match(call[1]!, /ceilingMs:\s*runtime\.store\.virtualTimeMs/);
  // Under a HIDE_* policy the dialog drops the date field and every time it would show.
  assert.match(shell, /hideDates=\{viewNavigation === "relative"\}/);
  assert.match(shell, /const publicTimePolicy = replayPublicTimePolicy\(/);
});
