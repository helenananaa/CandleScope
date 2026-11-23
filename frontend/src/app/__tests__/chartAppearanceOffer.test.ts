import assert from "node:assert/strict";
import test from "node:test";
import { shouldOfferChartTheme } from "../useChartAppearanceOffer.js";

test("the app theme is offered once, only when every chart sets the same other theme on its own", () => {
  assert.equal(shouldOfferChartTheme("light", "dark", false), true);
  assert.equal(shouldOfferChartTheme("dark", "system", false), true);
  assert.equal(shouldOfferChartTheme("light", "light", false), false, "the app already uses it");
  assert.equal(shouldOfferChartTheme(null, "dark", false), false, "charts differ or follow the app");
  assert.equal(shouldOfferChartTheme("light", "dark", true), false, "already checked on an earlier launch");
});
