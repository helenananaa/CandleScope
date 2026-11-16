import assert from "node:assert/strict";
import test from "node:test";
import { checkCssLayers, manifestProblems, selfLayeredProblems } from "./check-css-layers.mjs";

test("the app's stylesheets are all in cascade layers", () => {
  assert.deepEqual(checkCssLayers(), []);
});

test("a stylesheet outside a layer is reported with its first rule", () => {
  assert.deepEqual(selfLayeredProblems("@layer features { .a { color: red } }", "ok.css"), []);
  assert.match(selfLayeredProblems(".a { color: red }", "loose.css")[0], /loose\.css:1: \.a is outside a cascade layer/);
  assert.match(selfLayeredProblems("@layer theme { .a {} }", "odd.css")[0], /unknown layer "theme"/);
});

test("the manifest only imports files into known layers, after the layer order", () => {
  assert.deepEqual(manifestProblems('@import "./styles/layers.css";\n@import "./a.css" layer(features);').problems, []);
  assert.match(manifestProblems('@import "./a.css" layer(features);').problems[0], /first import must be \.\/styles\/layers\.css/);
  assert.match(manifestProblems('@import "./styles/layers.css";\n@import "./a.css";').problems[0], /needs layer/);
  assert.match(manifestProblems('@import "./styles/layers.css";\n.a { color: red }').problems[0], /only @import lines/);
});
