import assert from "node:assert/strict";
import test from "node:test";

import { dataAgeLevel, formatDataAge } from "../cellDataAgeModel.js";

test("data age stays quiet while fresh and escalates once a cell falls behind", () => {
  assert.equal(dataAgeLevel(3), "fresh");
  assert.equal(dataAgeLevel(10), "aging");
  assert.equal(dataAgeLevel(59.9), "aging");
  assert.equal(dataAgeLevel(60), "stale");
});

test("data age formats compactly by its largest unit", () => {
  assert.equal(formatDataAge(12.7), "12s");
  assert.equal(formatDataAge(185), "3m");
  assert.equal(formatDataAge(7200), "2h");
});
