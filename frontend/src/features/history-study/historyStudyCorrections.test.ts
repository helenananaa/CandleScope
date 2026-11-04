import assert from "node:assert/strict";
import test from "node:test";
import { studyInputHasChanged } from "./historyStudyCorrections.js";
import type { StudyBar } from "./historyStudyTypes.js";
import type { KlineBar } from "../market-data/marketDataTypes.js";

test("JSON object ordering is not a historical correction; actual fact and coverage changes are", () => {
  const saved: StudyBar[] = [60, 180].map(time => ({ time, closeTimeMs: (time + 60) * 1000,
    open: 10, high: 12, low: 9, close: 11, volume: 5, is_closed: true,
    order_flow: { taker_buy_ratio_base: .4, cvd_contribution_base: -1, volume_delta_base: -1, taker_sell_base: 3 } }));
  const current = saved.map(row => ({ ...row, quote_volume: null,
    order_flow: { taker_sell_base: 3, volume_delta_base: -1, taker_buy_ratio_base: .4, cvd_contribution_base: -1 } })) as unknown as KlineBar[];
  assert.equal(studyInputHasChanged(saved,current),false);
  assert.equal(studyInputHasChanged(saved,[{ ...current[0]!, volume: 6 }]),true);
  assert.equal(studyInputHasChanged(saved,[{ ...current[0]!, trades: 0 }]),true);
  assert.equal(studyInputHasChanged(saved,[{ ...current[0]!, order_flow: { ...current[0]!.order_flow!, cvd_contribution_base: 1 } }]),true);
  assert.equal(studyInputHasChanged(saved,[{ ...current[0]!, time: 240 as KlineBar["time"] }]),false);
  assert.equal(studyInputHasChanged(saved,[{ ...current[0]!, time: 120 as KlineBar["time"] }]),true);
  assert.equal(studyInputHasChanged(saved,[{ ...current[0]!, close: 100, is_closed: false }]),false);
});
