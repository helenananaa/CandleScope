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
  assert.deepEqual(internalTerms("zh-CN", "正在从后端读取规则"), ["后端"]);
  assert.deepEqual(internalTerms("en", "Reading rules from the backend"), ["backend"]);
});

test("the baseline only shrinks: new terms and stale entries both fail", () => {
  const catalogs = {
    "zh-CN": { listed: "存储 GC 预演", fixed: "已重写", added: "预览 lane 已满" },
    en: { listed: "Storage GC dry-run", fixed: "Rewritten", added: "Fine" },
  };
  assert.deepEqual(internalTermKeys(catalogs), { "zh-CN": ["added", "listed"], en: ["listed"] });
  assert.deepEqual(internalTermProblems(catalogs, { "zh-CN": ["fixed", "listed"], en: ["listed"] }), [
    "internal term in zh-CN:added (lane); use the user term from COPY_GUIDELINES.md",
    "remove zh-CN:fixed from scripts/i18n-internal-terms-baseline.json (no internal term left)",
  ]);
});
