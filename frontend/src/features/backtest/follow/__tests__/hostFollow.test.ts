import assert from "node:assert/strict";
import test from "node:test";
import { FollowContractError, holdFollow, parseHeldFollow, type FollowHoldPorts } from "../hostFollow.js";

const tick = () => new Promise((resolve) => setTimeout(resolve, 0));

class Gone extends Error {}

/** Ports whose sleeps the test releases one at a time. */
function ports(options: { holds: Array<unknown | Error>; renewals?: Array<Error | null> }) {
  const calls: string[] = [];
  const naps: Array<{ ms: number; wake: () => void }> = [];
  const readiness = new Map<string, () => void>();
  const value: FollowHoldPorts = {
    async hold(body) {
      calls.push(`hold ${JSON.stringify(body)}`);
      const next = options.holds.shift();
      if (next instanceof Error) throw next;
      return next;
    },
    async renew(followId, holder) {
      calls.push(`renew ${followId} ${holder}`);
      const next = options.renewals?.shift() ?? null;
      if (next) throw next;
      return { held: true };
    },
    async release(followId, holder) { calls.push(`release ${followId} ${holder}`); },
    ready(followId, signal) {
      return new Promise((resolve, reject) => {
        readiness.set(followId, resolve);
        signal.addEventListener("abort", () => reject(new Error("aborted")), { once: true });
      });
    },
    gone: (failure) => failure instanceof Gone,
    sleep(ms, signal) {
      return new Promise((resolve, reject) => {
        naps.push({ ms, wake: resolve });
        signal.addEventListener("abort", () => reject(new Error("aborted")), { once: true });
      });
    },
  };
  return { value, calls, naps, readiness };
}

const held = (id: string) => ({ follow_id: id, created: true, from_ms: 600_000, lease_ms: 30_000 });

test("a hold reply is validated", () => {
  assert.deepEqual(parseHeldFollow(held("fl_a")), { followId: "fl_a", fromMs: 600_000, leaseMs: 30_000 });
  for (const wrong of [{ ...held("bt_a") }, { ...held("fl_a"), lease_ms: 0 }, { ...held("fl_a"), from_ms: -1 }, null]) {
    assert.throws(() => parseHeldFollow(wrong), FollowContractError);
  }
});

test("a cell holds the run, shows it once it caught up, renews at a third of its lease and lets it go", async () => {
  const fake = ports({ holds: [held("fl_a")] });
  const shown: string[] = [];
  const controller = new AbortController();
  const done = holdFollow(fake.value, { run_id: "bt_1" }, "cell", (value) => shown.push(value.followId), controller.signal);
  await tick();
  assert.deepEqual(fake.calls, ['hold {"run_id":"bt_1","holder":"cell"}'], "the hold names the cell holding it");
  assert.deepEqual(shown, [], "nothing is shown before the run has a result");
  fake.readiness.get("fl_a")!();
  await tick();
  assert.deepEqual(shown, ["fl_a"]);
  assert.equal(fake.naps[0]!.ms, 10_000);
  fake.naps[0]!.wake();
  await tick();
  assert.equal(fake.calls.at(-1), "renew fl_a cell");
  controller.abort();
  await assert.rejects(done);
  assert.equal(fake.calls.at(-1), "release fl_a cell", "letting go releases the lease");
});

test("a run the backend forgot is held again and the new one shown; other renewal failures retry", async () => {
  const fake = ports({ holds: [held("fl_a"), held("fl_b")], renewals: [new Error("network"), new Gone()] });
  const shown: string[] = [];
  const controller = new AbortController();
  const done = holdFollow(fake.value, {}, "cell", (value) => shown.push(value.followId), controller.signal);
  await tick();
  for (let nap = 0; nap < 2; nap += 1) { fake.naps[nap]!.wake(); await tick(); await tick(); }
  assert.deepEqual(fake.calls.filter((call) => call.startsWith("hold")).length, 2, "held again after the run was gone");
  fake.readiness.get("fl_a")!();  // the old run's readiness arrives late
  fake.readiness.get("fl_b")!();
  await tick();
  assert.deepEqual(shown, ["fl_b"], "a replaced run is never shown");
  controller.abort();
  await assert.rejects(done);
  assert.equal(fake.calls.at(-1), "release fl_b cell");
});

test("a refused input rejects and holds nothing", async () => {
  const fake = ports({ holds: [new Error("BUDGET_EXCEEDED")] });
  await assert.rejects(holdFollow(fake.value, {}, "cell", () => assert.fail("not shown"), new AbortController().signal),
    /BUDGET_EXCEEDED/);
  assert.equal(fake.calls.filter((call) => call.startsWith("release")).length, 0);
});
