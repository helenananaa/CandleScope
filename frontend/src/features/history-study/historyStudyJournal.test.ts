import assert from "node:assert/strict";
import test from "node:test";
import { HistoryStudyDataManager } from "./historyStudyDataManager.js";
import type { StudyJournalData, StudyJournalFilters } from "./historyStudyJournal.js";

const series = { exchange: "binance", marketType: "spot", symbol: "BTCUSDT", interval: "1m" };
const { exchange, marketType, symbol } = series;
const all: StudyJournalFilters = { noteSource: "all", noteFilter: "all" };
const filtered: StudyJournalFilters = { noteSource: "original", noteFilter: "screenshots" };
const projection = (accountId: string, cursorMs: number, filters = all): StudyJournalData => ({
  accountId, cursorMs, exchange, marketType, symbol, ...filters, original: [], reviews: [], hasMore: false,
});

test("source-journal readers share manager cancellation without cancelling a sibling or falling back to public history", async () => {
  const reads: { account: string; cursor: number; filters: StudyJournalFilters; signal: AbortSignal; resolve(value: StudyJournalData): void }[] = [];
  const manager = new HistoryStudyDataManager(async () => { throw new Error("Public study transport must not serve an account journal"); },
    (account, _series, cursor, filters, signal) => new Promise(resolve => reads.push({ account, cursor, filters, signal, resolve })));
  const observer = new AbortController();
  const first = manager.journalAtTime("a", series, 1000, all, observer.signal);
  const second = manager.journalAtTime("a", series, 500, filtered);
  observer.abort(); reads[0]!.resolve(projection("a", 1000));
  await assert.rejects(first, { name: "AbortError" });
  assert.equal(reads[1]!.signal.aborted, false);
  assert.deepEqual(reads[1]!.filters, filtered);
  reads[1]!.resolve(projection("a", 500, filtered));
  assert.deepEqual(await second, projection("a", 500, filtered));
  const third = manager.journalAtTime("b", series, 1000, all);
  manager.dispose(); reads[2]!.resolve(projection("b", 1000));
  await assert.rejects(third, { name: "AbortError" });
  assert.deepEqual(manager.diagnostics(), { requests: 0, closed: true });
});

test("late/mismatched account and cursor projections are rejected instead of rebinding their text", async () => {
  for (const value of [projection("b", 1000), projection("a", 2000), projection("a", 1000, filtered),
    { ...projection("a", 1000), symbol: "ETHUSDT" }, { ...projection("a", 1000), marketType: "futures" },
    { ...projection("a", 1000), exchange: "okx" }, { ...projection("a", 1000), original: [{
    id: "foreign", accountId: "b", marketTimeMs: 1, createdAtMs: 1, savedAtMs: 1, revision: 1,
    fields: {}, body: "foreign text", reviewNote: false, historyUnavailable: false,
  }] }]) {
    const manager = new HistoryStudyDataManager(undefined, async () => value);
    await assert.rejects(manager.journalAtTime("a", series, 1000, all), /does not match/);
    assert.equal(manager.diagnostics().requests, 0);
  }
});

test("account journal uses the canonical instrument in the request and projection identity", async () => {
  const manager = new HistoryStudyDataManager(undefined, async (account, instrument, cursor, filters) => {
    assert.deepEqual(instrument, series);
    return projection(account, cursor, filters);
  });
  assert.deepEqual(await manager.journalAtTime("a", { ...series, exchange: " Binance ", marketType: " SPOT ", symbol: " btcusdt " },
    1000, filtered), projection("a", 1000, filtered));
});
