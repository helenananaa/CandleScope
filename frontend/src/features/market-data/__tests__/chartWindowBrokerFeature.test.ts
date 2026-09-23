import assert from "node:assert/strict";
import test from "node:test";

import { resolveChartWindowBrokerEnabled } from "../chartWindowBrokerFeature.js";

test("window broker defaults on and preserves strict explicit rollback", () => {
  assert.equal(resolveChartWindowBrokerEnabled(), true);
  for (const value of ["0", false, 0, "", null, "invalid"]) {
    assert.equal(resolveChartWindowBrokerEnabled({ CHART_WINDOW_BROKER_ENABLED: value }), false);
  }
  assert.equal(resolveChartWindowBrokerEnabled({ CHART_WINDOW_BROKER_ENABLED: "true" }), false);
  assert.equal(resolveChartWindowBrokerEnabled({ CHART_WINDOW_BROKER_ENABLED: "1" }), true);
  assert.equal(resolveChartWindowBrokerEnabled({ CHART_WINDOW_BROKER_ENABLED: true }), true);
});
