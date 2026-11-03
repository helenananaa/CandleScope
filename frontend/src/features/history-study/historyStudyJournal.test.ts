import assert from "node:assert/strict";
import test from "node:test";
import { HistoryStudyDataManager } from "./historyStudyDataManager.js";
import type { StudyJournalData } from "./historyStudyJournal.js";

const series = { exchange: "binance", marketType: "spot", symbol: "BTCUSDT", interval: "1m" };
const projection = (accountId: string, cursorMs: number): StudyJournalData => ({ accountId, cursorMs, original: [], reviews: [], hasMore: false });

test("source-journal readers share manager cancellation without cancelling a sibling or falling back to public history", async () => {
  const reads: { account: string; cursor: number; signal: AbortSignal; resolve(value: StudyJournalData): void }[] = [];
  const manager = new HistoryStudyDataManager(async () => { throw new Error("Public study transport must not serve an account journal"); },
    (account, _series, cursor, signal) => new Promise(resolve => reads.push({ account, cursor, signal, resolve })));
  const observer = new AbortController();
  const first = manager.journalAtTime("a", series, 1000, observer.signal);
  const second = manager.journalAtTime("a", series, 500);
  observer.abort(); reads[0]!.resolve(projection("a", 1000));
  await assert.rejects(first, { name: "AbortError" });
  assert.equal(reads[1]!.signal.aborted, false);
  reads[1]!.resolve(projection("a", 500));
  assert.deepEqual(await second, projection("a", 500));
  const third = manager.journalAtTime("b", series, 1000);
  manager.dispose(); reads[2]!.resolve(projection("b", 1000));
  await assert.rejects(third, { name: "AbortError" });
  assert.deepEqual(manager.diagnostics(), { requests: 0, closed: true });
});

test("late/mismatched account and cursor projections are rejected instead of rebinding their text", async () => {
  for (const value of [projection("b", 1000), projection("a", 2000), { ...projection("a", 1000), original: [{
    id: "foreign", accountId: "b", marketTimeMs: 1, createdAtMs: 1, savedAtMs: 1, revision: 1,
    fields: {}, body: "foreign text", reviewNote: false, historyUnavailable: false,
  }] }]) {
    const manager = new HistoryStudyDataManager(undefined, async () => value);
    await assert.rejects(manager.journalAtTime("a", series, 1000), /does not match/);
    assert.equal(manager.diagnostics().requests, 0);
  }
});
