import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { ReplayIndicatorProgress } from "../src/features/replay/replayIndicatorProgress.js";

type Case = { sessionId: string; request: { source_sequence: number; history_epoch: string;
  bars: { open_time_ms: number }[] }; expected: [string, unknown[]][] };
const input = JSON.parse(readFileSync(process.argv[2]!, "utf8")) as { origin: string; cases: Case[] };
let preparing = 0, contexts = 0, trades = 0;
for (const item of input.cases) {
  const progress = new ReplayIndicatorProgress();
  let completed = false;
  for (let attempt = 0; attempt < 100; attempt++) {
    const response = await fetch(`${input.origin}/api/v1/replay/runs/session/${item.sessionId}/indicator-compute`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(item.request),
    });
    const body = await response.json() as { protocol: string; status: string; seed: { history_epoch: string };
      source_preparation?: { phase: string }; payload: { lines: { name: string; data: unknown[] }[] } };
    assert.ok(response.ok, JSON.stringify(body));
    assert.equal(body.protocol, "replay.v3");
    assert.equal(body.seed.history_epoch, item.request.history_epoch);
    if (body.status === "preparing") {
      progress.advance(body, item.request.bars[0]!.open_time_ms, item.request.source_sequence);
      preparing++;
      if (body.source_preparation?.phase === "context") contexts++;
      if (body.source_preparation?.phase === "trades") trades++;
      continue;
    }
    assert.equal(body.status, "ready");
    assert.deepEqual(body.payload.lines.map(line => [line.name, line.data]), item.expected);
    completed = true;
    break;
  }
  assert.ok(completed, "canonical tape source did not finish");
}
console.log(JSON.stringify({ status: "PASS", comparisons: input.cases.length, preparing, contexts, trades }));
