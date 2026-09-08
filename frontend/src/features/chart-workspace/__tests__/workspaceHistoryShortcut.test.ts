import assert from "node:assert/strict";
import test from "node:test";
import { workspaceHistoryShortcut } from "../workspaceHistoryShortcut.js";
const event = { key: "z", ctrlKey: false, metaKey: true, altKey: false, shiftKey: false, defaultPrevented: false };
const state = { enabled: true, editable: false, canUndo: true, canRedo: true };
test("workspace panel supports Mac and Windows history shortcuts", () => {
  assert.equal(workspaceHistoryShortcut(event, state), "undo");
  assert.equal(workspaceHistoryShortcut({ ...event, ctrlKey: true, metaKey: false }, state), "undo");
  assert.equal(workspaceHistoryShortcut({ ...event, shiftKey: true }, state), "redo");
  assert.equal(workspaceHistoryShortcut({ ...event, key: "y" }, state), "redo");
});
test("editing, handled events, locked layouts and unavailable history are left alone", () => {
  assert.equal(workspaceHistoryShortcut(event, { ...state, editable: true }), null);
  assert.equal(workspaceHistoryShortcut(event, { ...state, enabled: false }), null);
  assert.equal(workspaceHistoryShortcut(event, { ...state, canUndo: false }), null);
  assert.equal(workspaceHistoryShortcut({ ...event, shiftKey: true }, { ...state, canRedo: false }), null);
  assert.equal(workspaceHistoryShortcut({ ...event, defaultPrevented: true }, state), null);
  assert.equal(workspaceHistoryShortcut({ ...event, altKey: true }, state), null);
  assert.equal(workspaceHistoryShortcut({ ...event, metaKey: false }, state), null);
});
