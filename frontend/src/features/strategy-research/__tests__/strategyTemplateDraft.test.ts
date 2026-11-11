import assert from "node:assert/strict";
import test from "node:test";
import { StrategyDraftStore, createMemoryStrategyDraftAdapter } from "../../backtest/chart-tester/StrategyDraftStore.js";
import { RESEARCH_STRATEGY_TEMPLATES, saveResearchTemplate } from "../strategyTemplateDraft.js";

test("template choice survives data selection and reopening without replacing earlier drafts", async () => {
  const adapter = createMemoryStrategyDraftAdapter();
  const store = new StrategyDraftStore(adapter);
  const saved = [];
  for (const template of RESEARCH_STRATEGY_TEMPLATES) saved.push(await saveResearchTemplate(store, template.id));
  assert.equal(new Set(saved.map((draft) => draft.id)).size, RESEARCH_STRATEGY_TEMPLATES.length);
  assert.deepEqual(saved.map((draft) => draft.language), ["python", "pine"]);
  const reopened = new StrategyDraftStore(adapter);
  for (const [index, template] of RESEARCH_STRATEGY_TEMPLATES.entries()) {
    const view = await reopened.load(saved[index]!.id);
    assert.equal(view.record?.source, template.source);
    assert.equal(view.record?.displayName, template.displayName);
    assert.equal(view.record?.language, template.language);
  }
  await assert.rejects(saveResearchTemplate(store, "unknown"));
});
