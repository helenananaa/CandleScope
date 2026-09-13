import test from "node:test";
import assert from "node:assert/strict";
import { parsePortfolioCurve } from "../portfolioCurve.js";
import { buildEquityPolyline } from "../replayIntegrityModel.js";

const response = () => ({ protocol: "replay.v3", run_id: "run-1", scope: "RECORDED_PORTFOLIO_INTERVALS",
  complete_training_history: false, available: true, span_ms: 120000,
  samples: [{ offset_ms: 60000, equity: "10000.00000001" }, { offset_ms: 120000, equity: "9999.99999999" }],
  summary: { max_drawdown: "0.00000002" } });

test("portfolio curve preserves precise values and bounded coverage", () => {
  const value = parsePortfolioCurve(response());
  assert.equal(value.summary?.max_drawdown, "0.00000002");
  assert.equal(buildEquityPolyline(value.samples, 420, 112), "0,0 420,112");
});

test("portfolio curve rejects future points, wrong coverage and numeric money", () => {
  assert.throws(() => parsePortfolioCurve({ ...response(), span_ms: 1 }));
  assert.throws(() => parsePortfolioCurve({ ...response(), complete_training_history: true }));
  assert.throws(() => parsePortfolioCurve({ ...response(), samples: [{ offset_ms: 0, equity: 10000 }] }));
});
