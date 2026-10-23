import assert from "node:assert/strict";
import test from "node:test";
import { pollNativeReplay } from "./nativeReplayPolling.js";
import type { NativeReplayRecord } from "./NativeReplayControls.js";

const current: NativeReplayRecord = { replay_id: "replay", run_id: "run", state: "RUNNING", revision: 4,
  cursor: 2, total: 10, result: null, snapshots: [], error: null };

test("polling keeps a cached report only for its exact replay revision and cursor", async () => {
  const fetchBefore = globalThis.fetch;
  try {
    let reply: unknown = { ...current, result_unchanged: true };
    globalThis.fetch = async (input) => {
      assert.match(String(input), /replays\/replay\?if_revision=4$/);
      return new Response(JSON.stringify(reply));
    };
    assert.deepEqual(await pollNativeReplay(current), current);
    reply = { ...current, state: "PAUSED", revision: 5, cursor: 3, result: null };
    assert.deepEqual(await pollNativeReplay(current), reply);
    reply = { ...current, cursor: 3, result_unchanged: true };
    await assert.rejects(pollNativeReplay(current), /revision differs/);
    reply = { ...current, replay_id: "another", result_unchanged: true };
    await assert.rejects(pollNativeReplay(current), /revision differs/);
  } finally { globalThis.fetch = fetchBefore; }
});
