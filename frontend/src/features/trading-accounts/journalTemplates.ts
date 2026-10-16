import type { MessageKey } from "../../i18n/index.js";
import type { JournalStage } from "./tradingTypes.js";

/**
 * Journal templates. Field keys are a contract with the backend: the risk
 * fields (entryPrice, stopPrice, targetPrice, riskUsdt) are locked at the
 * first fill, and the review fields mark a trade as reviewed.
 *
 * `auto` fields are never stored as text. They render live from the ledger so
 * they cannot go stale or be edited away; Markdown export freezes them.
 */
export type TemplateFieldKind = "text" | "longText" | "price" | "number" | "choice" | "auto";

export type AutoBinding =
  | "time"
  | "instrument"
  | "netResult"
  | "excursion"
  | "costs";

export interface TemplateChoice {
  readonly value: string;
  readonly labelKey: MessageKey;
}

export interface TemplateField {
  readonly key: string;
  readonly labelKey: MessageKey;
  readonly kind: TemplateFieldKind;
  readonly auto?: AutoBinding;
  readonly choices?: readonly TemplateChoice[];
  readonly hintKey?: MessageKey;
}

export interface TemplateSection {
  readonly id: "info" | "pre" | "post" | "review";
  readonly titleKey: MessageKey;
  /** Earliest stage at which the section is shown expanded. */
  readonly stage: JournalStage;
  readonly fields: readonly TemplateField[];
}

export interface JournalTemplate {
  readonly id: string;
  readonly version: number;
  readonly sections: readonly TemplateSection[];
}

export const RISK_FIELD_KEYS = ["entryPrice", "stopPrice", "targetPrice", "riskUsdt"] as const;
export const PRE_TRADE_FIELD_KEYS = [
  ...RISK_FIELD_KEYS,
  "timeframe",
  "strategyTag",
  "marketEnv",
  "entryBasis",
  "expectedPath",
  "invalidation",
] as const;

export const TRADE_REVIEW_TEMPLATE: JournalTemplate = {
  id: "trade-review",
  version: 1,
  sections: [
    {
      id: "info",
      titleKey: "trading.tpl.info",
      stage: "pre",
      fields: [
        { key: "time", labelKey: "trading.tpl.time", kind: "auto", auto: "time" },
        { key: "instrument", labelKey: "trading.tpl.instrument", kind: "auto", auto: "instrument" },
        { key: "timeframe", labelKey: "trading.tpl.timeframe", kind: "text" },
        { key: "strategyTag", labelKey: "trading.tpl.strategyTag", kind: "text" },
        { key: "entryPrice", labelKey: "trading.tpl.entryPrice", kind: "price" },
        { key: "stopPrice", labelKey: "trading.tpl.stopPrice", kind: "price" },
        { key: "targetPrice", labelKey: "trading.tpl.targetPrice", kind: "price" },
        { key: "riskUsdt", labelKey: "trading.tpl.riskUsdt", kind: "number", hintKey: "trading.tpl.riskHint" },
      ],
    },
    {
      id: "pre",
      titleKey: "trading.tpl.pre",
      stage: "pre",
      fields: [
        {
          key: "marketEnv",
          labelKey: "trading.tpl.marketEnv",
          kind: "choice",
          choices: [
            { value: "trending", labelKey: "trading.tpl.env.trending" },
            { value: "ranging", labelKey: "trading.tpl.env.ranging" },
            { value: "uncertain", labelKey: "trading.tpl.env.uncertain" },
          ],
        },
        { key: "entryBasis", labelKey: "trading.tpl.entryBasis", kind: "longText" },
        { key: "expectedPath", labelKey: "trading.tpl.expectedPath", kind: "longText" },
        { key: "invalidation", labelKey: "trading.tpl.invalidation", kind: "longText" },
      ],
    },
    {
      id: "post",
      titleKey: "trading.tpl.post",
      stage: "post",
      fields: [
        { key: "netResult", labelKey: "trading.tpl.netResult", kind: "auto", auto: "netResult" },
        { key: "excursion", labelKey: "trading.tpl.excursion", kind: "auto", auto: "excursion" },
        { key: "costs", labelKey: "trading.tpl.costs", kind: "auto", auto: "costs" },
        {
          key: "adherence",
          labelKey: "trading.tpl.adherence",
          kind: "choice",
          choices: [
            { value: "yes", labelKey: "trading.tpl.adherence.yes" },
            { value: "partial", labelKey: "trading.tpl.adherence.partial" },
            { value: "no", labelKey: "trading.tpl.adherence.no" },
            { value: "noPlan", labelKey: "trading.tpl.adherence.noPlan" },
          ],
        },
        { key: "deviations", labelKey: "trading.tpl.deviations", kind: "longText" },
      ],
    },
    {
      id: "review",
      titleKey: "trading.tpl.review",
      stage: "post",
      fields: [
        { key: "goodDecisions", labelKey: "trading.tpl.goodDecisions", kind: "longText" },
        { key: "errors", labelKey: "trading.tpl.errors", kind: "longText" },
        { key: "hypotheses", labelKey: "trading.tpl.hypotheses", kind: "longText" },
      ],
    },
  ],
};

export function templateFor(id: string | null | undefined): JournalTemplate {
  void id;
  return TRADE_REVIEW_TEMPLATE;
}

const STAGE_ORDER: Record<JournalStage, number> = { pre: 0, open: 1, post: 2 };

/** Sections relevant now are expanded; later ones stay collapsed until then. */
export function sectionExpanded(section: TemplateSection, stage: JournalStage): boolean {
  return STAGE_ORDER[stage] >= STAGE_ORDER[section.stage];
}

/** Risk-per-trade suggestion for linear contracts: qty × |entry − stop|. */
export function suggestedRisk(entry: string, stop: string, qty: string): string | null {
  const e = Number(entry);
  const s = Number(stop);
  const q = Number(qty);
  if (!Number.isFinite(e) || !Number.isFinite(s) || !Number.isFinite(q) || q <= 0 || e === s) return null;
  return (Math.abs(e - s) * q).toFixed(2);
}
