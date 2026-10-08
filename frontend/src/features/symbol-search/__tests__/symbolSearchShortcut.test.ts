import assert from "node:assert/strict";
import test from "node:test";
import { quickSearchCharacter, searchKeyboardBlocked } from "../symbolSearchShortcut.js";

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

test("an open shortcut dialog still protects focused editors and other dialogs", () => {
  const picker = { getClientRects: () => [1] } as unknown as HTMLElement;
  const otherDialog = { getClientRects: () => [1] } as unknown as HTMLElement;
  let editing = false;
  let dialogs = [picker];
  const document = {
    activeElement: { closest: () => editing ? {} : null },
    querySelectorAll: () => dialogs,
  } as unknown as Document;
  const event = { ...key("2"), composedPath: () => [] } as unknown as KeyboardEvent;
  const originalStyle = Object.getOwnPropertyDescriptor(globalThis, "getComputedStyle");
  Object.defineProperty(globalThis, "getComputedStyle", {
    configurable: true,
    value: () => ({ visibility: "visible" }),
  });
  try {
    assert.equal(searchKeyboardBlocked(document, event), true, "a closed page shortcut respects dialogs");
    assert.equal(searchKeyboardBlocked(document, event, picker), false, "rapid digits before picker autofocus are accepted");
    editing = true;
    assert.equal(searchKeyboardBlocked(document, event, picker), true, "custom amount and search inputs keep their digits");
    editing = false;
    dialogs = [picker, otherDialog];
    assert.equal(searchKeyboardBlocked(document, event, picker), true, "another visible dialog still blocks the shortcut");
  } finally {
    if (originalStyle) Object.defineProperty(globalThis, "getComputedStyle", originalStyle);
    else Reflect.deleteProperty(globalThis, "getComputedStyle");
  }
});
