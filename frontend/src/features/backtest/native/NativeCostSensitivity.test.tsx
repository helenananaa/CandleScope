import assert from "node:assert/strict";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { t } from "../../../i18n/index.js";
import { NativeCostSensitivity, type NativeCostMatrix } from "./NativeCostSensitivity.js";

const matrix = (): NativeCostMatrix => ({ status: "COMPLETED", baseline_reexecution_verified: true,
  scenarios: [{ name: "BASELINE", status: "COMPLETED", executed: true,
    metrics: { fill_count: 2, fee_total: ".25", ending_equity: "123.45", ending_position: "3" } },
  { name: "LATENCY_PLUS_ONE_TIER", status: "NOT_APPLICABLE_BAR_CLOCK", executed: false,
    metrics: { fill_count: 999999, fee_total: "999999", ending_equity: "999999", ending_position: "999999" } }] });

test("verified cost tables show executed metrics and leave inapplicable rows unavailable", () => {
  const html = renderToStaticMarkup(<NativeCostSensitivity matrix={matrix()} />);
  assert.match(html, /123.45/);
  assert.ok(html.includes(t("native.cost.notApplicable")));
  assert.doesNotMatch(html, /999999/);
  assert.match(html, /scope="row"/);
});

test("old, skipped and unverified reports never fabricate a completed matrix", () => {
  assert.equal(renderToStaticMarkup(<NativeCostSensitivity matrix={undefined} />), "");
  assert.equal(renderToStaticMarkup(<NativeCostSensitivity matrix={{ ...matrix(), baseline_reexecution_verified: false }} />), "");
  const html = renderToStaticMarkup(<NativeCostSensitivity matrix={{ ...matrix(), status: "SKIPPED_BY_REQUEST", scenarios: [] }} />);
  assert.ok(html.includes(t("native.cost.skipped")));
  assert.doesNotMatch(html, /<table/);
});

test("nonfinite and unknown scenario data cannot render misleading numbers or markup", () => {
  const value = matrix();
  value.scenarios[0]!.metrics.ending_equity = "NaN";
  value.scenarios[0]!.name = "__proto__";
  const html = renderToStaticMarkup(<NativeCostSensitivity matrix={value} />);
  assert.doesNotMatch(html, /NaN|Infinity/);
  assert.ok(html.includes(t("native.cost.unknown")));
});
