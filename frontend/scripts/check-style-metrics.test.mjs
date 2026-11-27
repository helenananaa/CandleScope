import assert from "node:assert/strict";
import test from "node:test";

import { RATCHETS, RAW_BUTTON_EXCEPTIONS, classNamesInCss, classNamesInTsx, collectMetrics, importantOutsideReducedMotion, isStaticStyleObject, malformedSelectorLines, strictFailures } from "./check-style-metrics.mjs";

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
  const clean = { unstyledClasses: 0, important: 0, nativeDialogs: 0, legacyColorTokens: 0, malformedSelectors: 0, staticInlineStyles: 0, rawButtons: 0, staleRawButtonExceptions: [], ...RATCHETS };
  assert.deepEqual(strictFailures(clean), []);
  assert.deepEqual(strictFailures({ ...clean, buttonClassFamilies: RATCHETS.buttonClassFamilies - 5 }), []);
  assert.deepEqual(strictFailures({ ...clean, important: 1, rawButtons: 1, buttonClassFamilies: RATCHETS.buttonClassFamilies + 1 }), [
    "important is 1, target 0",
    "rawButtons is 1, target 0",
    `buttonClassFamilies is ${RATCHETS.buttonClassFamilies + 1}, above its ratchet of ${RATCHETS.buttonClassFamilies}`,
  ]);
});

test("raw buttons count only beyond a file's documented exceptions, and a stale exception fails strict mode", () => {
  const [file, allowed] = Object.entries(RAW_BUTTON_EXCEPTIONS)[0];
  const buttons = (count) => "<button />".repeat(count);
  const kept = collectMetrics([`/repo/src/${file}`], () => buttons(allowed));
  assert.equal(kept.rawButtons, 0);
  assert.equal(kept.rawButtonExceptions, allowed);
  assert.deepEqual(kept.staleRawButtonExceptions.filter((name) => name === file), []);
  const extra = collectMetrics([`/repo/src/${file}`, "/repo/src/features/New.tsx"], (path) => path.endsWith("New.tsx") ? buttons(1) : buttons(allowed + 1));
  assert.equal(extra.rawButtons, 2);
  const fewer = collectMetrics([`/repo/src/${file}`], () => buttons(allowed - 1));
  assert.ok(fewer.staleRawButtonExceptions.includes(file));
  assert.ok(strictFailures({ ...fewer, buttonClassFamilies: 0 }).some((line) => line.includes(file)));
});

test("selectors with unbalanced brackets are reported by line; strings and keyframes are skipped", () => {
  const css = `.a :is(b, c):where(:not(.x, .y)) { color: red; }
.hub :is(button, a):where(:not(.ui-btn, .ui-icon-btn)), .ui-icon-btn)) { color: red; }
.ui-icon-btn)) { color: blue; }
[data-label="("] { color: green; }
@keyframes spin { from { opacity: 0; } to { opacity: 1; } }`;
  assert.deepEqual(malformedSelectorLines(css), [2, 3]);
});

test("static inline styles hold only literal values; computed values and shorthand names are dynamic", () => {
  assert.equal(isStaticStyleObject(' fontSize: 48 '), true);
  assert.equal(isStaticStyleObject(' color: "var(--text-primary)", marginTop: 8, display: "block" '), true);
  assert.equal(isStaticStyleObject(' "--accent": "#fff" '), true);
  assert.equal(isStaticStyleObject(' height '), false);
  assert.equal(isStaticStyleObject(' width: `${width}%` '), false);
  assert.equal(isStaticStyleObject(' display: open ? undefined : "none" '), false);
  assert.equal(isStaticStyleObject(' "--chart-link-group-color": group.color '), false);
});

test("component metrics skip browser-test harnesses", () => {
  const files = {
    "/src/A.tsx": '<div style={{ padding: 16 }} /><div style={{ width }} />',
    "/src/drawings/tools.browser.tsx": '<div style={{ width: 1000 }}><button /></div>',
  };
  const metrics = collectMetrics(Object.keys(files), (file) => files[file]);
  assert.equal(metrics.inlineStyles, 2);
  assert.equal(metrics.staticInlineStyles, 1);
  assert.equal(metrics.rawButtons, 0);
});
