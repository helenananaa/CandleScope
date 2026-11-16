// Internal terms in user-facing copy (Phase 6, see COPY_GUIDELINES.md).
//
// The source catalogs (zh-CN, en) must not show engineering vocabulary: status codes,
// storage and runtime internals, or English jargon inside Chinese text. Phase 6 rewrote every
// message that did, so the check is a plain rule: any message using a term below fails.

/** Terms that are jargon in both source locales. Placeholders such as {revision} are ignored. */
const SHARED_TERMS: ReadonlyArray<readonly [string, RegExp]> = [
  ["status code", /\b[A-Z][A-Z0-9]*_[A-Z0-9_]{2,}\b/],
  ["backend", /\bbackends?\b/i],
  ["receipt", /\breceipts?\b/i],
  ["bundle", /\bbundles?\b/i],
  ["epoch", /\bepoch\b|dataEpoch/i],
  ["payload", /\bpayload\b/i],
  ["schema", /\bschema\b/i],
  ["smoke", /\bsmoke\b/i],
  ["checksum", /\bchecksum\b/i],
  ["dry-run", /\bdry-run\b/i],
  ["GC", /\bGC\b/],
  ["VACUUM", /\bVACUUM\b/],
  ["WAL", /\bWAL\b/],
  ["SQLite", /\bSQLite\b/],
  ["Decimal", /\bDecimal\b/],
  ["VirtualTime", /VirtualTime/],
  ["fidelity", /\bfidelity\b/i],
  ["fail-closed", /fail-closed|失败关闭/i],
  ["lane", /\blane\b/i],
  ["evaluator", /\bevaluator\b/i],
  ["blob", /\bblob\b/i],
  ["class name", /IndicatorEngine|WorkspaceBus|TradeFlow|DataManager|DataEngine|BacktestRun|StrategyRevision|ReviewMode/],
  ["Top-N", /\bTop-N\b/i],
  ["project phase", /\bPhase \d+/],
  ["Study V2", /\bStudy V2\b/],
  ["flag", /\bflags?\b/i],
  ["hash", /\bhash\b/i],
  ["revision", /\brevisions?\b/i],
  ["queue exact", /\bqueue exact\b/i],
  ["raw trade", /\braw trades?\b/i],
  ["holdout", /\bholdout\b/i],
];

/** English words that are jargon inside Chinese text, and Chinese engineering terms. */
const CHINESE_TERMS: ReadonlyArray<readonly [string, RegExp]> = [
  ["runtime", /\bruntimes?\b/i],
  ["exact", /\bexact\b/i],
  ["pin", /\bpin(?:ned)?\b/i],
  ["overlay", /\boverlay\b/i],
  ["ledger", /\bledger\b/i],
  ["native / custom", /\bnative\b|\bcustom\b/i],
  ["ticker", /\bticker\b/i],
  ["Canvas", /\bcanvas\b/i],
  ["closed bars", /\bclosed bars?\b/i],
  ["Run", /\bRuns?\b/],
  ["Study", /\bStud(?:y|ies)\b/],
  ["trace", /\btraces?\b/i],
  ["manifest", /\bmanifest\b/i],
  ["warmup", /\bwarm-?up\b/i],
  ["provider", /\bproviders?\b/i],
  ["snapshot", /\bsnapshots?\b/i],
  ["tick", /\bticks?\b/i],
  ["后端", /后端/],
  ["影子", /影子/],
  ["权威", /权威/],
  ["信任门", /信任门/],
  ["死信", /死信/],
  ["水化", /水化/],
  ["保活", /保活/],
];

export const SOURCE_LOCALES = ["zh-CN", "en"] as const;
export type SourceLocale = typeof SOURCE_LOCALES[number];

/** Names of the internal terms a message uses, in list order. */
export function internalTerms(locale: SourceLocale, message: string): string[] {
  const text = message.replace(/\{[A-Za-z0-9_]+\}/g, " ");
  const terms = locale === "zh-CN" ? [...SHARED_TERMS, ...CHINESE_TERMS] : SHARED_TERMS;
  return terms.filter(([, pattern]) => pattern.test(text)).map(([name]) => name);
}

/** Keys of each source catalog whose message uses an internal term. */
export function internalTermKeys(
  catalogs: Readonly<Record<string, Readonly<Record<string, string>>>>,
): Record<SourceLocale, string[]> {
  const result = { "zh-CN": [] as string[], en: [] as string[] };
  for (const locale of SOURCE_LOCALES) {
    for (const [key, message] of Object.entries(catalogs[locale] ?? {})) {
      if (internalTerms(locale, message).length > 0) result[locale].push(key);
    }
    result[locale].sort();
  }
  return result;
}

/** One problem per source message that uses an internal term. */
export function internalTermProblems(
  catalogs: Readonly<Record<string, Readonly<Record<string, string>>>>,
): string[] {
  const problems: string[] = [];
  const found = internalTermKeys(catalogs);
  for (const locale of SOURCE_LOCALES) {
    for (const key of found[locale]) {
      const terms = internalTerms(locale, catalogs[locale]![key]!).join(", ");
      problems.push(`internal term in ${locale}:${key} (${terms}); use the user term from COPY_GUIDELINES.md`);
    }
  }
  return problems;
}
