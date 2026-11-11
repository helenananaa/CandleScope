import assert from "node:assert/strict";
import test from "node:test";
import { normalizeChartAccountOverlay } from "../../chart-workspace/chartAccountOverlaySettings.js";
import { replayChartTradeInputs } from "../replayChartTradeInputs.js";
import type { ReplayFill, ReplayOrder } from "../replayTypes.js";
import type { ReplayTrainingPortfolioV1 } from "../replayV2Types.js";

const earlierFill = { fill_id: "earlier", event_time_ms: 1000 } as ReplayFill;
const currentFill = { fill_id: "current", event_time_ms: 2000 } as ReplayFill;
const futureOrder = { order_id: "future", created_time_ms: 2001 } as ReplayOrder;
const currentOrder = { order_id: "current", created_time_ms: 2000 } as ReplayOrder;
const store = {
  sessionId: "adapter-btc", hasAuthoritativeSnapshot: true, virtualTimeMs: 2000,
  sourceSequence: 8, revision: 12, fills: [earlierFill, currentFill], orders: [currentOrder, futureOrder],
};
const track = { adapter_session_id: "adapter-btc", cursor: { virtual_time_ms: 2000, source_sequence: 8, revision: 12 } };
const portfolio: ReplayTrainingPortfolioV1 = {
  schema_version: "replay.training.portfolio.v1", fidelity: "PAPER_LINEAR_V1_MULTI_TRACK_ADAPTER",
  settlement_account_shared: true, position_mode: "ONE_WAY", positions: [],
  initial_equity: "100", equity: "100", cash_balance: "100", available_equity: "100",
  reserved_margin: "0", margin_used: "0", realized_pnl: "0", unrealized_pnl: "0", fees_paid: "0",
};
const empty = { fills: [], orders: [], portfolio: undefined };

test("a replay chart shows only fills at its revealed boundary and current positions at the matching adapter revision", () => {
  assert.deepEqual(replayChartTradeInputs(store, 1000, track, portfolio, undefined), { ...empty, fills: [earlierFill] });
  assert.deepEqual(replayChartTradeInputs(store, 2000, track, portfolio, undefined), {
    fills: [earlierFill, currentFill], orders: [currentOrder], portfolio,
  });
  const ahead = { ...track, cursor: { ...track.cursor, revision: 13 } };
  assert.deepEqual(replayChartTradeInputs(store, 2000, ahead, portfolio, undefined), {
    fills: [earlierFill, currentFill], orders: [currentOrder], portfolio: undefined,
  });
});

test("chart display options and track authority gate independent overlay inputs", () => {
  const hiddenFills = normalizeChartAccountOverlay({ trades: false });
  assert.deepEqual(replayChartTradeInputs(store, 2000, track, portfolio, hiddenFills), {
    fills: [], orders: [currentOrder], portfolio,
  });
  const hiddenPositions = normalizeChartAccountOverlay({ positions: false });
  assert.deepEqual(replayChartTradeInputs(store, 2000, track, portfolio, hiddenPositions), {
    ...empty, fills: [earlierFill, currentFill],
  });
  assert.deepEqual(replayChartTradeInputs(store, null, track, portfolio, undefined), empty);
  assert.deepEqual(replayChartTradeInputs(store, 2000, { ...track, adapter_session_id: "adapter-eth" }, portfolio, undefined), empty);
  assert.deepEqual(replayChartTradeInputs({ ...store, hasAuthoritativeSnapshot: false }, 2000, track, portfolio, undefined), empty);
});
