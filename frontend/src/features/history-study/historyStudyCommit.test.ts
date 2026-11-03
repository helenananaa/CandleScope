import assert from "node:assert/strict";
import test from "node:test";
import { commitStudyView } from "./historyStudyCommit.js";
import type { HistoryStudyView } from "./historyStudyTypes.js";

const before: HistoryStudyView = { revision: 4, active: false, cursorMs: null, study: null };
const target: HistoryStudyView = { revision: 5, active: true, cursorMs: 600_000,
  study: { id: "hs_saved", series: { exchange: "binance", marketType: "spot", symbol: "BTCUSDT", interval: "1m" },
    capturedAtMs: 1, inputKind: "captured-market-history", rows: [] } };
const matches = (view: HistoryStudyView) => view.active && view.study?.id === target.study!.id
  && view.cursorMs === target.cursorMs;

test("committed capture with a dropped acknowledgement is recovered without a second write", async () => {
  let durable = before, writes = 0, masked = false;
  const result = await commitStudyView({ before, matches, current: () => true,
    uncertain: () => { masked = true; }, read: async () => { assert.equal(masked, true); return durable; },
    write: async () => { writes++; durable = target; throw new Error("response lost"); } });
  assert.equal(result, target);
  assert.equal(writes, 1);
});

test("only an exact unchanged authoritative view permits one retry", async () => {
  let writes = 0, reads = 0;
  const result = await commitStudyView({ before, matches, current: () => true, uncertain: () => {},
    read: async () => { reads++; return before; },
    write: async () => { if (++writes === 1) throw new Error("request lost"); return target; } });
  assert.equal(result, target); assert.equal(writes, 2); assert.equal(reads, 1);
});

test("a competing revision or contradictory identity, active state, or cursor is never retried", async () => {
  for (const authoritative of [
    { ...target, revision: 6 }, { ...target, active: false }, { ...target, cursorMs: 540_000 },
    { ...target, study: { ...target.study!, id: "hs_other" } },
    { ...before, cursorMs: 540_000 }, { ...before, active: true },
  ]) {
    let writes = 0;
    await assert.rejects(commitStudyView({ before, matches, current: () => true, uncertain: () => {},
      read: async () => authoritative, write: async () => { writes++; throw new Error("unknown"); } }), /study_commit_conflict/);
    assert.equal(writes, 1);
  }
});

test("an unavailable read or repeated transport failure leaves the write unresolved and masked", async () => {
  for (const readFails of [false, true]) {
    let writes = 0, masked = false;
    await assert.rejects(commitStudyView({ before, matches, current: () => true,
      uncertain: () => { masked = true; },
      read: async () => { if (readFails) throw new Error("read unavailable"); return before; },
      write: async () => { writes++; throw new Error("transport unavailable"); } }), /unavailable/);
    assert.equal(masked, true); assert.equal(writes, readFails ? 1 : 2);
  }
});

test("owner teardown during reconciliation cannot retry a write in the old workspace", async () => {
  let active = true, writes = 0;
  await assert.rejects(commitStudyView({ before, matches, current: () => active, uncertain: () => {},
    read: async () => { active = false; return before; },
    write: async () => { writes++; throw new Error("response lost"); } }), /study_context_changed/);
  assert.equal(writes, 1);
});

test("a malformed success acknowledgement is checked against the authoritative view", async () => {
  let masked = false;
  assert.equal(await commitStudyView({ before, matches, current: () => true,
    uncertain: () => { masked = true; }, write: async () => ({ ...target, revision: 99 }),
    read: async () => target }), target);
  assert.equal(masked, true);
});
