import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { aggregateReplayBaseBars } from "../src/features/replay/replayViewerProjection.js";
import { replayDisplayBarToKline } from "../src/features/replay/replaySeriesProjection.js";
import type { ReplayDisplayBar } from "../src/features/replay/replayTypes.js";
import type { ReplayDigest } from "../src/features/replay/replayTypes.js";
import { ReplayV2ApiClient } from "../src/features/replay/replayV2Api.js";
import { loadReplayTapeProjection, type ReplayTapeProjectionRequest } from "../src/features/replay/replayTapeProjection.js";

type Case = { base: string; interval: string; rows: ReplayDisplayBar[]; actual: ReplayDisplayBar[]; limit: number;
  sessionId?: string; request?: ReplayTapeProjectionRequest; beforeMs?: number; paginate?: boolean };
const input = JSON.parse(readFileSync(process.argv[2]!, "utf8")) as Case[] | { origin: string; cases: Case[] };
const cases = Array.isArray(input) ? input : input.cases;
const api = Array.isArray(input) ? null : new ReplayV2ApiClient({ basePath: `${input.origin}/api/v1/replay` });
let preparing = 0;
const fields = ["time", "sourceFromTime", "sourceToTime", "open", "high", "low", "close", "volume", "quoteVolume", "trades", "takerBuyBase", "takerBuyQuote",
  "replayCloseTimeMs", "replayLastBaseOpenMs", "replayComponentCount", "replayExpectedComponents", "replayClosed", "replaySynthetic"];
for (const item of cases) {
  const all = aggregateReplayBaseBars(item.rows.map(replayDisplayBarToKline), item.base, item.interval)
    .filter(row => item.beforeMs === undefined || Number(row.time) * 1000 < item.beforeMs);
  const expected = item.paginate ? all : all.slice(-item.limit);
  let actual = !item.paginate && api && item.sessionId && item.request
    ? (await loadReplayTapeProjection(signal => api.tapeProjectionBySession(item.sessionId!, item.request!, signal),
      new AbortController().signal, () => { preparing++; })).bars : item.actual;
  if (item.paginate) {
    assert.ok(api && item.sessionId && item.request);
    let beforeMs: number | undefined;
    let historyEpoch: ReplayDigest | undefined;
    let more = true;
    actual = [];
    for (let page = 0; more && page < 100; page++) {
      const response = await loadReplayTapeProjection(signal => api.tapeProjectionBySession(item.sessionId!, {
        ...item.request!, ...(beforeMs === undefined ? {} : { beforeMs }), ...(historyEpoch === undefined ? {} : { historyEpoch }),
      }, signal), new AbortController().signal, () => { preparing++; });
      assert.equal(typeof response.has_more, "boolean");
      assert.notEqual(response.next_before_ms, null);
      if (beforeMs !== undefined) assert.ok(response.next_before_ms! < beforeMs || !response.has_more);
      if (response.bars.length && actual.length) assert.ok(response.bars.at(-1)!.open_time_ms < actual[0]!.open_time_ms);
      actual = [...response.bars, ...actual];
      beforeMs = response.next_before_ms!;
      historyEpoch = response.history_epoch;
      more = response.has_more!;
    }
    assert.equal(more, false, "tape history must terminate");
  }
  const select = (row: ReturnType<typeof replayDisplayBarToKline>) => fields.map(key => row[key]);
  assert.deepEqual(actual.map(replayDisplayBarToKline).map(select), expected.map(select), item.interval);
}
console.log(JSON.stringify({ comparisons: cases.length, preparing, status: "PASS" }));
