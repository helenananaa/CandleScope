import assert from "node:assert/strict";
import test from "node:test";
import {
  fixedIntervalMs, followInputKey, followRange, latestClosedBarOpenMs, SCRIPT_FOLLOW_BAR_BUDGET, ScriptFollowController,
  type FollowRange, type ScriptFollowBase,
} from "../scriptFollow.js";

const MINUTE = 60_000;

function window(lastOpenSeconds: number | null, closed: boolean | undefined) {
  return {
    intervalSeconds: 60,
    last: () => lastOpenSeconds === null ? null : ({ time: lastOpenSeconds, is_closed: closed }) as never,
  };
}

test("the newest closed bar is the last bar once it closes, else the one before it", () => {
  assert.equal(latestClosedBarOpenMs(window(600, true)), 600_000);
  assert.equal(latestClosedBarOpenMs(window(600, false)), 540_000);
  assert.equal(latestClosedBarOpenMs(window(null, true)), null);
  assert.equal(latestClosedBarOpenMs(window(600, undefined)), null, "a bar without finality is not trusted");
  assert.equal(latestClosedBarOpenMs(null), null);
});

test("a rebuild keeps the user's start until the bar budget slides it, ending at the closed bar's close", () => {
  assert.deepEqual(followRange(0, 10 * MINUTE, MINUTE), { start_time_ms: 0, end_time_ms: 11 * MINUTE - 1 });
  const far = (SCRIPT_FOLLOW_BAR_BUDGET + 99) * MINUTE;
  const slid = followRange(0, far, MINUTE);
  assert.equal(slid.start_time_ms, far - (SCRIPT_FOLLOW_BAR_BUDGET - 1) * MINUTE);
  assert.equal((slid.end_time_ms + 1 - slid.start_time_ms) / MINUTE, SCRIPT_FOLLOW_BAR_BUDGET, "exactly the budget's bars");
  assert.equal(fixedIntervalMs("1m"), MINUTE);
  assert.equal(fixedIntervalMs("4h"), 4 * 60 * MINUTE);
  assert.equal(fixedIntervalMs("1d"), 24 * 60 * MINUTE);
  assert.equal(fixedIntervalMs("1w"), null, "calendar intervals are not followed");
  assert.equal(fixedIntervalMs("1M"), null);
});

test("the idempotency key is the input's identity", async () => {
  const one = await followInputKey({ b: 1, a: { y: [1, 2], x: "s" } });
  assert.match(one, /^follow-[0-9a-f]{64}$/);
  assert.equal(await followInputKey({ a: { x: "s", y: [1, 2] }, b: 1 }), one, "key order does not matter");
  assert.notEqual(await followInputKey({ b: 2, a: { y: [1, 2], x: "s" } }), one);
  assert.ok(one.length <= 128, "fits the run creation key limit");
});

function base(calls: FollowRange[], outcome: (range: FollowRange, signal: AbortSignal) => Promise<string | null>): ScriptFollowBase<string> {
  return { startMs: 0, coveredEndMs: 10 * MINUTE - 1, intervalMs: MINUTE,
    rebuild(range, signal) { calls.push(range); return outcome(range, signal); } };
}

const tick = () => new Promise((resolve) => setTimeout(resolve, 0));

test("each newer closed bar rebuilds once; closes during a rebuild fold into one more", async () => {
  const calls: FollowRange[] = [], shown: string[] = [];
  let release: (() => void) | undefined;
  const controller = new ScriptFollowController<string>((run) => shown.push(run), (failure) => assert.fail(String(failure)));
  controller.setBase(base(calls, async (range) => {
    if (calls.length === 1) await new Promise<void>((resolve) => { release = resolve; });
    return `run-to-${(range.end_time_ms + 1) / MINUTE}`;
  }));
  controller.setClosedBar(9 * MINUTE);  // already covered
  assert.equal(calls.length, 0);
  controller.setClosedBar(10 * MINUTE);
  assert.equal(calls.length, 1);
  controller.setClosedBar(11 * MINUTE);
  controller.setClosedBar(12 * MINUTE);
  assert.equal(calls.length, 1, "one rebuild at a time");
  release?.();
  await tick(); await tick();
  assert.deepEqual(calls.map((range) => (range.end_time_ms + 1) / MINUTE), [11, 13], "the folded rebuild covers the newest close");
  assert.deepEqual(shown, ["run-to-11", "run-to-13"]);
  controller.dispose();
});

test("a replaced base abandons its rebuild; data not ready and failures wait for the next bar", async () => {
  const calls: FollowRange[] = [], shown: string[] = [], failures: unknown[] = [];
  let release: (() => void) | undefined;
  const controller = new ScriptFollowController<string>((run) => shown.push(run), (failure) => failures.push(failure));
  controller.setBase(base(calls, async (_range, signal) => {
    await new Promise<void>((resolve) => { release = resolve; });
    assert.equal(signal.aborted, true);
    return "stale";
  }));
  controller.setClosedBar(10 * MINUTE);
  controller.setBase(null);  // the user started another run
  release?.();
  await tick();
  assert.deepEqual(shown, [], "an abandoned rebuild is never shown");

  const outcomes: Array<string | null | Error> = [null, new Error("engine busy"), "run-to-13"];
  const tried: FollowRange[] = [];
  controller.setBase(base(tried, async () => {
    const next = outcomes.shift()!;
    if (next instanceof Error) throw next;
    return next;
  }));
  await tick();
  assert.equal(tried.length, 1, "the newer closed bar is rebuilt for the new base");
  await tick();
  controller.setClosedBar(11 * MINUTE);
  await tick(); await tick();
  assert.equal(failures.length, 1);
  controller.setClosedBar(12 * MINUTE);
  await tick(); await tick();
  assert.deepEqual(shown, ["run-to-13"]);
  controller.dispose();
});

test("a disposed controller follows again once resumed (StrictMode remounts effects)", async () => {
  const calls: FollowRange[] = [];
  const controller = new ScriptFollowController<string>(() => undefined, () => undefined);
  controller.dispose();
  controller.setBase(base(calls, async () => "run"));
  controller.setClosedBar(10 * MINUTE);
  assert.equal(calls.length, 0, "a disposed controller does not rebuild");
  controller.resume();
  assert.equal(calls.length, 1);
  controller.dispose();
});

test("an extendable rebuild's start is kept until the window would exceed twice the budget", () => {
  const budget = SCRIPT_FOLLOW_BAR_BUDGET;
  const first = followRange(0, (budget + 99) * MINUTE, MINUTE);
  const kept = followRange(0, (budget + 100) * MINUTE, MINUTE, budget, first.start_time_ms);
  assert.equal(kept.start_time_ms, first.start_time_ms, "the next rebuild continues the previous input");
  const longest = followRange(0, first.start_time_ms + (2 * budget - 1) * MINUTE, MINUTE, budget, first.start_time_ms);
  assert.equal((longest.end_time_ms + 1 - longest.start_time_ms) / MINUTE, 2 * budget, "at most twice the budget");
  const restarted = followRange(0, first.start_time_ms + 2 * budget * MINUTE, MINUTE, budget, first.start_time_ms);
  assert.equal((restarted.end_time_ms + 1 - restarted.start_time_ms) / MINUTE, budget, "then the latest budget's bars again");
  assert.equal(followRange(5 * MINUTE, 20 * MINUTE, MINUTE, budget, 0).start_time_ms, 5 * MINUTE,
    "never before the user's start");
});

test("the start is kept only after a rebuild the engine can extend", async () => {
  const budget = SCRIPT_FOLLOW_BAR_BUDGET;
  const calls: FollowRange[] = [];
  const extendable: string[] = [];
  const controller = new ScriptFollowController<string>(() => undefined, (failure) => assert.fail(String(failure)));
  const followed: ScriptFollowBase<string> = {
    startMs: 0, coveredEndMs: (budget + 99) * MINUTE, intervalMs: MINUTE,
    async rebuild(range) { calls.push(range); return calls.length === 2 ? "full-only" : "extendable"; },
    extendable: (run) => { extendable.push(run); return run === "extendable"; },
  };
  controller.setBase(followed);
  for (let bar = budget + 100; bar < budget + 104; bar += 1) {
    controller.setClosedBar(bar * MINUTE);
    await tick(); await tick();
  }
  const starts = calls.map((range) => range.start_time_ms / MINUTE);
  // 1st: sliding window; 2nd keeps it; the 2nd could not be extended, so the 3rd slides; the 4th keeps the 3rd's.
  assert.deepEqual(starts, [101, 101, 103, 103]);
  assert.deepEqual(extendable, ["extendable", "full-only", "extendable", "extendable"]);
  controller.setBase({ ...followed, coveredEndMs: (budget + 104) * MINUTE - 1 });
  controller.setClosedBar((budget + 104) * MINUTE);
  await tick();
  assert.equal(calls.at(-1)!.start_time_ms / MINUTE, 105, "a new base starts with the sliding window");
  controller.dispose();
});
