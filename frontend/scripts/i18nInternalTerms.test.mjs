import assert from "node:assert/strict";
import test from "node:test";
import { internalTermKeys, internalTermProblems, internalTerms } from "./i18nInternalTerms.mts";

test("internal terms: status codes and engineering words, not placeholders", () => {
  assert.deepEqual(internalTerms("zh-CN", "保留策略版本 {revision}"), []);
  assert.deepEqual(internalTerms("en", "Run {runId} finished"), []);
  assert.deepEqual(internalTerms("zh-CN", "单向净持仓（ONE_WAY）"), ["status code"]);
  assert.deepEqual(internalTerms("en", "Metrics hash {hash}"), ["hash"]);
  assert.deepEqual(internalTerms("zh-CN", "WorkspaceBus 单写入者"), ["class name"]);
  assert.deepEqual(internalTerms("zh-CN", "完全订阅：ticker + {native} native"), ["native / custom", "ticker"]);
});

test("English words that are jargon in Chinese text are ordinary words in English", () => {
  assert.deepEqual(internalTerms("zh-CN", "按已揭示价格 exact 结算"), ["exact"]);
  assert.deepEqual(internalTerms("en", "Exact fills use the trade tape"), []);
  assert.deepEqual(internalTerms("en", "The Pine runtime restarted"), []);
  assert.deepEqual(internalTerms("zh-CN", "插件随包 runtime"), ["runtime"]);
  // Research objects and data terms (Phase 6c2): English words inside Chinese, and "authority".
  assert.deepEqual(internalTerms("zh-CN", "校验并创建 Run"), ["Run"]);
  assert.deepEqual(internalTerms("zh-CN", "Study 草稿 · 载入有界信号 trace"), ["Study", "trace"]);
  assert.deepEqual(internalTerms("zh-CN", "按权威对象重置"), ["权威"]);
  assert.deepEqual(internalTerms("en", "Reveal holdout"), ["holdout"]);
  assert.deepEqual(internalTerms("en", "Created run {id}."), []);
  assert.deepEqual(internalTerms("zh-CN", "正在从后端读取规则"), ["后端"]);
  assert.deepEqual(internalTerms("en", "Reading rules from the backend"), ["backend"]);
});

test("every source message with an internal term is a problem", () => {
  const catalogs = {
    "zh-CN": { storage: "存储 GC 预演", fixed: "已重写", preview: "预览 lane 已满" },
    en: { storage: "Storage GC dry-run", fixed: "Rewritten", preview: "Fine" },
  };
  assert.deepEqual(internalTermKeys(catalogs), { "zh-CN": ["preview", "storage"], en: ["storage"] });
  assert.deepEqual(internalTermProblems(catalogs), [
    "internal term in zh-CN:preview (lane); use the user term from COPY_GUIDELINES.md",
    "internal term in zh-CN:storage (GC); use the user term from COPY_GUIDELINES.md",
    "internal term in en:storage (dry-run, GC); use the user term from COPY_GUIDELINES.md",
  ]);
});
