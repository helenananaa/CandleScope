import assert from "node:assert/strict";
import test from "node:test";

import { RATCHETS, classNamesInCss, classNamesInTsx, collectMetrics, importantOutsideReducedMotion, malformedSelectorLines, strictFailures } from "./check-style-metrics.mjs";

test("TSX class extraction reads plain and conditional className values", () => {
  const names = classNamesInTsx(`
    <div className="panel panel-wide" />
    <button className={active ? "tab is-active" : "tab"} />
    <span className={\`badge \${tone}\`} />
    <a className={buttonClassName({ variant: "primary", className: "x" })} />
  `);
  assert.deepEqual([...names].sort(), ["badge", "is-active", "panel", "panel-wide", "tab", "ui-btn"]);
});

test("TSX class extraction skips values that are compared to choose a class", () => {
  const names = classNamesInTsx(`
    <small className={side === "short" ? "negative" : side === "long" ? "positive" : undefined} />
    <td className={["profit", "net_pnl"].includes(column) ? "signed" : undefined} />
    <path className={"drawdown" === metric ? "line-down" : "line"} />
  `);
  assert.deepEqual([...names].sort(), ["line", "line-down", "negative", "positive", "signed"]);
});

test("CSS extraction ignores comments and finds every selector class", () => {
  const names = classNamesInCss("/* .ghost */ .panel > .tab:hover, .badge { color: red }");
  assert.deepEqual([...names].sort(), ["badge", "panel", "tab"]);
});

test("metrics flag unstyled classes, raw buttons and native dialogs", () => {
  const files = {
    "/src/a.css": ".panel { color: var(--text-primary) !important }",
    "/src/A.tsx": `<div className="panel orphan is-open"><button className="export-exclude">x</button></div>; window.confirm("?")`,
    "/src/components/ui/Button.tsx": "<button />",
  };
  const metrics = collectMetrics(Object.keys(files), (file) => files[file]);
  assert.equal(metrics.unstyledClasses, 1);
  assert.deepEqual(metrics.unstyled[0].classes, ["orphan"]);
  assert.equal(metrics.rawButtons, 1);
  assert.equal(metrics.important, 1);
  assert.equal(metrics.nativeDialogs, 1);
});

test("metrics count legacy colour token names in stylesheets and components, not theme contract keys", () => {
  const files = {
    "/src/a.css": ".panel { background: var(--bg-primary); border: 1px solid var(--border-color); border-color: red; }",
    "/src/B.tsx": 'export const B = () => <div style={{ background: "var(--bg-hover)" }} />;',
    "/src/theme.ts": 'export const MAP = { "bg-primary": "surface-0", "border-color": "border-subtle" };',
    "/src/ok.css": ".panel { background: var(--surface-0); border: 1px solid var(--border-subtle); }",
  };
  assert.equal(collectMetrics(Object.keys(files), (file) => files[file]).legacyColorTokens, 3);
});

test("!important counts skip comments and prefers-reduced-motion blocks", () => {
  const css = `/* no !important here */
.panel { color: red !important; }
@media (prefers-reduced-motion: reduce) { *, *::before { animation-duration: 0.01ms !important; transition: none !important; } }
@media (max-width: 900px) { .panel { width: 1px !important; } }`;
  assert.equal(importantOutsideReducedMotion(css), 2);
});

test("strict mode fails on a metric off its zero target or above its ratchet, not below it", () => {
  const clean = { unstyledClasses: 0, important: 0, nativeDialogs: 0, legacyColorTokens: 0, malformedSelectors: 0, ...RATCHETS };
  assert.deepEqual(strictFailures(clean), []);
  assert.deepEqual(strictFailures({ ...clean, rawButtons: RATCHETS.rawButtons - 5 }), []);
  assert.deepEqual(strictFailures({ ...clean, important: 1, inlineStyles: RATCHETS.inlineStyles + 1 }), [
    "important is 1, target 0",
    `inlineStyles is ${RATCHETS.inlineStyles + 1}, above its ratchet of ${RATCHETS.inlineStyles}`,
  ]);
});

test("selectors with unbalanced brackets are reported by line; strings and keyframes are skipped", () => {
  const css = `.a :is(b, c):where(:not(.x, .y)) { color: red; }
.hub :is(button, a):where(:not(.ui-btn, .ui-icon-btn)), .ui-icon-btn)) { color: red; }
.ui-icon-btn)) { color: blue; }
[data-label="("] { color: green; }
@keyframes spin { from { opacity: 0; } to { opacity: 1; } }`;
  assert.deepEqual(malformedSelectorLines(css), [2, 3]);
});
