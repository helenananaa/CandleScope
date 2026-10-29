import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { parseExchangeCapability } from "../../../services/apiPayloadParsers.js";
import { canResolveIntervalFromNativeValues } from "../../../utils/intervals.js";
import { buildExchangeCatalog, getNativeIntervals } from "../exchangeCatalogRuntime.js";

const fixture = JSON.parse(readFileSync(new URL("../../../../../backend/tests/fixtures/interval_admission.json", import.meta.url), "utf8")) as {
  documents: Array<{ capability: unknown; checks: Array<{
    target: string; market: string; purpose: "history" | "realtime"; kind: string;
  }> }>;
};
for (const document of fixture.documents) {
  const capability = parseExchangeCapability(document.capability);
  test(`shared wire admission: ${capability.exchange}`, () => {
    const catalog = buildExchangeCatalog([capability]);
    for (const check of document.checks) {
      const native = getNativeIntervals(capability.exchange, catalog, check.market, check.purpose);
      assert.equal(canResolveIntervalFromNativeValues(check.target, native.map(item => item.value)),
        check.kind !== "unavailable", JSON.stringify(check));
    }
  });
}
