import assert from "node:assert/strict";
import test from "node:test";
import { quickSearchCharacter } from "../symbolSearchShortcut.js";

const key = (value: string, extra = {}) => ({ key: value, ctrlKey: false, metaKey: false, altKey: false,
  isComposing: false, defaultPrevented: false, repeat: false, keyCode: 0, ...extra });

test("direct letters and digits preserve the opening character", () => {
  for (const value of ["b", "B", "t", "0", "9"]) assert.equal(quickSearchCharacter(key(value), false), value);
});

test("editing, handled shortcuts, modifiers and IME do not open search", () => {
  assert.equal(quickSearchCharacter(key("b"), true), null);
  for (const extra of [{ ctrlKey: true }, { metaKey: true }, { altKey: true },
    { isComposing: true }, { keyCode: 229 }, { defaultPrevented: true }, { repeat: true }]) {
    assert.equal(quickSearchCharacter(key("b", extra), false), null);
  }
});

test("navigation and punctuation do not become a quick search", () => {
  for (const value of ["Enter", "Escape", "Backspace", "ArrowUp", " ", "/", "!", "Dead", "Process"]) {
    assert.equal(quickSearchCharacter(key(value), false), null);
  }
});
