import assert from "node:assert/strict";
import test from "node:test";
import { createTrainingRunDraft } from "./trainingHubModel.js";
import { readHubDraft, writeHubDraft } from "./trainingHubDraftStorage.js";

test("draft restore retains exact fidelity and nullable random-start controls; rejects incompatible saved data", () => {
  let saved = "";
  const storage = { getItem: () => saved, setItem: (_key: string, text: string) => { saved = text; } };
  const draft = { ...createTrainingRunDraft(), startMode: "RANDOM" as const, requestedStartMs: null,
    accountDataMode: "HISTORICAL_EXACT" as const, name: "保留训练条件" };
  const value = { draft, submission: { identity: "frozen-request", key: "same-key-123" } };
  writeHubDraft(storage, "draft", value);
  assert.deepEqual(readHubDraft(storage, "draft"), value);
  saved = JSON.stringify({ version: 1, draft: { ...draft, accountDataMode: "UNKNOWN" } });
  assert.equal(readHubDraft(storage, "draft"), null);
  saved = JSON.stringify({ version: 1, draft: { ...draft, indicatorWarmupBars: "200" } });
  assert.equal(readHubDraft(storage, "draft"), null);
  saved = JSON.stringify({ version: 99, draft });
  assert.equal(readHubDraft(storage, "draft"), null);
});

test("restricted or corrupt browser storage does not prevent replay creation", () => {
  const blocked = { getItem: () => { throw new Error("denied"); }, setItem: () => { throw new Error("quota"); } };
  assert.equal(readHubDraft(blocked, "draft"), null);
  assert.doesNotThrow(() => writeHubDraft(blocked, "draft", { draft: createTrainingRunDraft(), submission: null }));
  assert.equal(readHubDraft({ getItem: () => "{bad", setItem() {} }, "draft"), null);
});


test("market random scope survives reload and older drafts retain range random behavior", () => {
  let saved = "";
  const storage = { getItem: () => saved, setItem: (_key: string, value: string) => { saved = value; } };
  const draft = { ...createTrainingRunDraft(), startMode: "RANDOM" as const, randomScope: "MARKET" as const, requestedStartMs: null };
  writeHubDraft(storage, "draft", { draft, submission: null });
  assert.equal(readHubDraft(storage, "draft")?.draft.randomScope, "MARKET");
  saved = JSON.stringify({ version: 1, draft: { ...draft, randomScope: undefined }, submission: null });
  assert.equal(readHubDraft(storage, "draft")?.draft.randomScope, "RANGE");
});
