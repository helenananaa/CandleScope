import assert from "node:assert/strict";
import test from "node:test";
import { BackfillRecoveryQueue } from "../feed/backfillRecoveryQueue.js";

type Job = { epoch: number; eventKeys: Set<string>; from: number; to: number; initial?: boolean };
const job = (epoch: number, id: string, from = 1, to = 2): Job => ({ epoch, eventKeys: new Set([id]), from, to, initial: true });
const deferred = () => {
  let resolve!: (value: boolean) => void;
  const promise = new Promise<boolean>((done) => { resolve = done; });
  return { promise, resolve };
};

test("cancelled old read cannot block, deduplicate or delete the successor queue", async () => {
  const old = deferred(); const fresh = deferred();
  const reads: number[] = []; const verified: number[] = [];
  let epoch = 1;
  const queue = new BackfillRecoveryQueue<Job>({
    merge: () => false,
    read: async (next) => { reads.push(next.epoch); return (next.epoch === 1 ? old : fresh).promise; },
    verify: async (next) => { verified.push(next.epoch); },
    needsVerification: () => true, isCurrent: (next) => next.epoch === epoch,
    cooldown: () => 3_000, onError: (error) => { throw error; },
  });
  queue.enqueue("btc", job(1, "same-event"));
  const oldDone = queue.whenIdle("btc");
  queue.cancel("btc"); epoch = 2;
  queue.enqueue("btc", job(2, "same-event"));
  assert.deepEqual(reads, [1, 2], "new read starts even while old cancellation is ignored");
  old.resolve(false); await oldDone;
  assert.equal(queue.activeKeys.has("btc"), true, "old finally cannot delete new owner");
  queue.enqueue("btc", job(2, "same-event"));
  assert.deepEqual(reads, [1, 2], "successor deduplication survives old completion");
  const newDone = queue.whenIdle("btc"); fresh.resolve(false); await newDone;
  assert.deepEqual(verified, [2]);
  assert.equal(queue.activeKeys.size, 0);
});

test("queued overlapping chunks merge and trigger one initial verification after all reads", async () => {
  const first = deferred(); const reads: number[][] = []; let verifies = 0;
  const queue = new BackfillRecoveryQueue<Job>({
    merge: (held, next) => {
      if (held.to < next.from || held.from > next.to) return false;
      held.from = Math.min(held.from, next.from); held.to = Math.max(held.to, next.to);
      next.eventKeys.forEach((id) => held.eventKeys.add(id)); return true;
    },
    read: async (next) => { reads.push([next.from, next.to]); return reads.length === 1 ? first.promise : false; },
    verify: async () => { verifies += 1; }, needsVerification: () => true,
    isCurrent: () => true, cooldown: () => 3_000, onError: (error) => { throw error; },
  });
  queue.enqueue("btc", job(1, "a", 1, 2));
  queue.enqueue("btc", job(1, "b", 3, 5));
  queue.enqueue("btc", job(1, "c", 4, 6));
  queue.enqueue("btc", job(1, "c", 4, 6));
  const done = queue.whenIdle("btc"); first.resolve(false); await done;
  assert.deepEqual(reads, [[1, 2], [3, 6]]);
  assert.equal(verifies, 1);
  queue.enqueue("btc", job(1, "b", 3, 5));
  assert.equal(reads.length, 2);
});
