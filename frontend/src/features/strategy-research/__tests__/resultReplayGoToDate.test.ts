import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { findResultReplayCursor, RESULT_REPLAY_SEARCH_PROBES } from "../resultReplayTimeSearch.js";

const MINUTE = 60_000;
const START = Date.UTC(2026, 0, 5);

/** Event times as the backend reports them: cursor c reveals event c - 1. */
function engine(times: readonly number[]) {
  const asked: number[] = [];
  return {
    asked,
    timeAt: (cursor: number) => {
      asked.push(cursor);
      assert.ok(cursor >= 1 && cursor <= times.length, `cursor ${cursor} outside the frozen input`);
      return Promise.resolve(times[cursor - 1]!);
    },
  };
}

test("a regular bar input lands on the bar at or before the target in a few probes", async () => {
  const times = Array.from({ length: 100_000 }, (_, index) => START + index * MINUTE);
  const run = engine(times);
  const found = await findResultReplayCursor(START + 54_321 * MINUTE + 30_000, times.length, run.timeAt, { toleranceMs: MINUTE });
  assert.deepEqual({ cursor: found?.cursor, timeMs: found?.timeMs, exact: found?.exact },
    { cursor: 54_322, timeMs: START + 54_321 * MINUTE, exact: true });
  assert.ok(found!.probes <= 6, `took ${found!.probes} probes`);
});

test("weekend gaps and clustered events still converge on the right cursor", async () => {
  const times: number[] = [];
  for (let day = 0; day < 60; day += 1) {
    if (day % 7 === 5 || day % 7 === 6) continue; // closed
    for (let minute = 0; minute < 390; minute += 1) times.push(START + day * 86_400_000 + 13.5 * 3_600_000 + minute * MINUTE);
  }
  // A burst of trades sharing one timestamp.
  times.splice(500, 0, ...Array.from({ length: 50 }, () => times[499]!));
  const saturday = START + 5 * 86_400_000 + 12 * 3_600_000;
  const run = engine(times);
  const found = await findResultReplayCursor(saturday, times.length, run.timeAt, { toleranceMs: MINUTE });
  const expected = times.filter((time) => time <= saturday).length;
  assert.equal(found?.cursor, expected);
  assert.equal(found?.exact, false, "a closed day reports the nearest bar");
  assert.ok(found!.probes <= 2 * Math.ceil(Math.log2(times.length)) + 2, `took ${found!.probes} probes`);
  const burst = await findResultReplayCursor(times[499]!, times.length, engine(times).timeAt);
  assert.equal(burst?.cursor, 550, "the last event of a same-time burst");
});

test("targets outside the input land on its ends, and a broken engine is reported", async () => {
  const times = [START, START + MINUTE, START + 2 * MINUTE];
  assert.deepEqual(await findResultReplayCursor(START - 1, 3, engine(times).timeAt), { cursor: 1, timeMs: START, exact: false, probes: 1 });
  const after = await findResultReplayCursor(START + 10 * MINUTE, 3, engine(times).timeAt, { toleranceMs: MINUTE });
  assert.equal(after?.cursor, 3);
  assert.equal(after?.exact, false);
  assert.equal(await findResultReplayCursor(START, 0, engine([]).timeAt), null);
  await assert.rejects(findResultReplayCursor(START + MINUTE, 3, () => Promise.resolve(null)), /no time/);
  // Every probe shrinks the range, so the search ends; the cap bounds a slow engine's requests.
  const long = Array.from({ length: 1_000_000 }, (_, index) => START + index * MINUTE);
  await assert.rejects(findResultReplayCursor(START + 777_777 * MINUTE, long.length, engine(long).timeAt, { maxProbes: 3 }), /did not converge/);
  assert.equal(RESULT_REPLAY_SEARCH_PROBES, 48);
});

test("strategy-result replay moves its own cursor, found through its own frames", () => {
  const replay = readFileSync(new URL("../StrategyResultReplay.tsx", import.meta.url), "utf8");
  assert.match(replay, /useGoToDateHotkey\(canGoToDate, /);
  assert.match(replay, /findResultReplayCursor\(timeMs, total,\s*async cursor => \(await manager\.loadResultReplay\(\{ \.\.\.probe, cursor \}, controller\.signal\)\)\.time_ms/);
  // Probes carry no references or studies: only run, snapshot, report and interval.
  assert.match(replay, /const probe = \{ runId: request\.runId, snapshotHash: request\.snapshotHash, reportHash: request\.reportHash, interval: request\.interval \};/);
  // The result goes through the replay's normal navigation, which reloads the frame at that cursor.
  assert.match(replay, /navigate\(found\.cursor\);/);
  // A newer search aborts an older one, and leaving the replay aborts it too.
  assert.match(replay, /dateSearch\.current\?\.abort\(\);\s*const controller = new AbortController\(\);/);
  assert.match(replay, /useEffect\(\(\) => \(\) => dateSearch\.current\?\.abort\(\), \[\]\);/);
});
