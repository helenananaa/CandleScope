import test from "node:test";
import assert from "node:assert/strict";
import { marketTrackProjectionIsOlder } from "../marketTrackProjectionOrder.js";

const projection = (revision: number, session = "s1", run = "r1") => ({
  run_id: run,
  global_clock: null,
  tracks: [{ adapter_session_id: session, cursor: { revision, source_sequence: revision, virtual_time_ms: revision } }],
});

test("delayed push cannot roll back an acknowledged market version", () => {
  assert.equal(marketTrackProjectionIsOlder(projection(9), projection(10)), true);
  assert.equal(marketTrackProjectionIsOlder(projection(10), projection(10)), false);
  assert.equal(marketTrackProjectionIsOlder(projection(11), projection(10)), false);
});

test("new run or replacement adapter does not inherit a previous revision floor", () => {
  assert.equal(marketTrackProjectionIsOlder(projection(1, "s2"), projection(10)), false);
  assert.equal(marketTrackProjectionIsOlder(projection(1, "s1", "r2"), projection(10)), false);
});

test("one stale member rejects the whole portfolio rather than mixing versions", () => {
  const before = { ...projection(10), tracks: [...projection(10).tracks, ...projection(20, "s2").tracks] };
  const next = { ...projection(11), tracks: [...projection(11).tracks, ...projection(19, "s2").tracks] };
  assert.equal(marketTrackProjectionIsOlder(next, before), true);
});

test("server recovery may reset playback counters without rewinding durable actors", () => {
  const before = { ...projection(10), global_clock: { generation: 3, profile_revision: 2, tick: 20 } };
  const after = { ...projection(10), global_clock: { generation: 0, profile_revision: 0, tick: 0 } };
  assert.equal(marketTrackProjectionIsOlder(after, before), false);
  assert.equal(marketTrackProjectionIsOlder({ ...after, ...projection(9) }, before), true);
});
