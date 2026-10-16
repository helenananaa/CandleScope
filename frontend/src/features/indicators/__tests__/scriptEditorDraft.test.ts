import assert from "node:assert/strict";
import test from "node:test";
import { createScriptEditorDraft, editScriptEditorSource, scriptEditorSource, switchScriptEditorLanguage } from "../scriptEditorDraft.js";

test("new draft waits for the selected runtime's starter, including late discovery", () => {
  const draft = createScriptEditorDraft("", false);
  assert.equal(scriptEditorSource(draft, "", ""), "");
  assert.equal(scriptEditorSource(draft, "pyne", "indicator(overlay=True)"), "indicator(overlay=True)");
  assert.equal(scriptEditorSource(draft, "pine", "//@version=6"), "//@version=6");
});

test("language roundtrip uses separate templates and retains edited and empty drafts", () => {
  let draft = createScriptEditorDraft("", false);
  draft = editScriptEditorSource(draft, "pyne", "plot(close, 'Custom')");
  draft = switchScriptEditorLanguage(draft, "pyne", scriptEditorSource(draft, "pyne", "pyne starter"), "pine", "pine starter");
  assert.equal(scriptEditorSource(draft, "pine", "new starter"), "pine starter");
  draft = editScriptEditorSource(draft, "pine", "");
  draft = switchScriptEditorLanguage(draft, "pine", "", "pyne", "pyne starter");
  assert.equal(scriptEditorSource(draft, "pyne", "pyne starter"), "plot(close, 'Custom')");
  draft = switchScriptEditorLanguage(draft, "pyne", "plot(close, 'Custom')", "pine", "pine starter");
  assert.equal(scriptEditorSource(draft, "pine", "pine starter"), "");
});

test("saved and forked source is never replaced by the runtime's starter", () => {
  for (const saved of [true, false]) {
    const draft = createScriptEditorDraft("saved source", saved);
    assert.equal(scriptEditorSource(draft, "pine", "starter"), "saved source");
  }
  assert.equal(scriptEditorSource(createScriptEditorDraft("", true), "pine", "starter"), "");
});

test("editing before discovery preserves the user's source", () => {
  const draft = editScriptEditorSource(createScriptEditorDraft("", false), "", "plot(close)");
  assert.equal(scriptEditorSource(draft, "pyne", "starter from late catalog"), "plot(close)");
});
