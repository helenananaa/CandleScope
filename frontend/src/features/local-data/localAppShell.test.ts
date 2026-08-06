import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";


test("local analysis reuses the shared indicator panel and drawing toolbar", () => {
  const directory = dirname(fileURLToPath(import.meta.url));
  const source = readFileSync(resolve(directory, "LocalApp.tsx"), "utf8");

  assert.match(source, /<IndicatorPanel/);
  assert.match(source, /staticCatalog=\{LOCAL_STATIC_INDICATOR_CATALOG\}/);
  assert.match(source, /<DrawingToolbar/);
  assert.match(source, /drawingTool=\{drawingTool\}/);
  assert.doesNotMatch(source, /LocalIndicatorPanel/);
});
