import assert from "node:assert/strict";
import test from "node:test";
import { shortcutModifier } from "../shortcutModifier.js";

test("keyboard hints use the primary modifier for the platform", () => {
  for (const platform of ["MacIntel", "MacARM", "iPad", "iPhone"]) assert.equal(shortcutModifier(platform), "⌘");
  for (const platform of ["Win32", "Linux x86_64", ""]) assert.equal(shortcutModifier(platform), "Ctrl");
});
