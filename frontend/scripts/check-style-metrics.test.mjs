import assert from "node:assert/strict";
import test from "node:test";

import { classNamesInCss, classNamesInTsx, collectMetrics } from "./check-style-metrics.mjs";

test("TSX class extraction reads plain and conditional className values", () => {
  const names = classNamesInTsx(`
    <div className="panel panel-wide" />
    <button className={active ? "tab is-active" : "tab"} />
    <span className={\`badge \${tone}\`} />
    <a className={buttonClassName({ variant: "primary", className: "x" })} />
  `);
  assert.deepEqual([...names].sort(), ["badge", "is-active", "panel", "panel-wide", "tab", "ui-btn"]);
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
