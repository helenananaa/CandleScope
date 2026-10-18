import { t } from "../../i18n/index.js";
import { TRADE_REVIEW_TEMPLATE, type TemplateField } from "./journalTemplates.js";
import { formatAmount, formatDateTime, formatPrice, formatSigned } from "./tradingFormat.js";
import type { Excursion, LinkSuggestion, TradeDetail } from "./tradingTypes.js";

export type PlanLevels = Pick<LinkSuggestion, "entryPrice" | "stopPrice" | "targetPrice" | "riskUsdt" | "direction">;

// What the backend's Decimal() accepts once trimmed (digit grouping aside).
const DECIMAL_TEXT = /^[+-]?(?:\d+\.?\d*|\.\d+)(?:e[+-]?\d+)?$/i;

function planDecimal(value: string | undefined): string | null {
  const text = value?.trim() ?? "";
  if (!DECIMAL_TEXT.test(text) || !Number.isFinite(Number(text))) return null;
  if (/e/i.test(text)) return String(Number(text));
  // Like the backend's dec_str, without trailing zeros; tiny prices keep their digits (no "1e-7").
  return text.replace(/^\+/, "").replace(/(\.\d*?)0+$/, "$1").replace(/\.$/, "");
}

/** A plan's latest risk fields, read as the backend does (risk_fields + plan_direction in journal.py). */
export function planLevels(fields: Record<string, string>): PlanLevels {
  const entryPrice = planDecimal(fields.entryPrice);
  const stopPrice = planDecimal(fields.stopPrice);
  const targetPrice = planDecimal(fields.targetPrice);
  const riskUsdt = planDecimal(fields.riskUsdt);
  // Plans have no side: stop below / target above entry implies long, and vice versa.
  const implied = new Set<"long" | "short">();
  if (entryPrice !== null) {
    const entry = Number(entryPrice);
    if (stopPrice !== null && Number(stopPrice) !== entry) implied.add(Number(stopPrice) < entry ? "long" : "short");
    if (targetPrice !== null && Number(targetPrice) !== entry) implied.add(Number(targetPrice) > entry ? "long" : "short");
  }
  const direction = implied.size === 1 ? [...implied][0]! : null;
  return { entryPrice, stopPrice, targetPrice, riskUsdt, direction };
}

/** "entry … · stop … · target … · risk …" parts; empty levels are left out. */
export function planLevelParts(plan: PlanLevels): string[] {
  const parts: string[] = [];
  if (plan.entryPrice !== null) parts.push(t("trading.journal.suggestion.entry", { value: formatPrice(plan.entryPrice) }));
  if (plan.stopPrice !== null) parts.push(t("trading.journal.suggestion.stop", { value: formatPrice(plan.stopPrice) }));
  if (plan.targetPrice !== null) parts.push(t("trading.journal.suggestion.target", { value: formatPrice(plan.targetPrice) }));
  if (plan.riskUsdt !== null) parts.push(t("trading.journal.suggestion.risk", { value: formatAmount(plan.riskUsdt) }));
  return parts;
}

/** Plans saved in the same minute share a time, so add what was planned; empty parts are left out. */
export function linkSuggestionLabel(item: LinkSuggestion): string {
  const parts = [t("trading.journal.linkPlan", { time: formatDateTime(item.createdAtMs) })];
  if (item.direction) parts.push(t(item.direction === "long" ? "trading.long" : "trading.short"));
  return [...parts, ...planLevelParts(item)].join(" · ");
}

export function journalMarkdown(
  fields: Record<string, string>,
  trade: TradeDetail | null,
  excursion: Excursion | null,
  instrumentLabel: string,
): string {
  const lines: string[] = [];
  for (const section of TRADE_REVIEW_TEMPLATE.sections) {
    lines.push(`## ${t(section.titleKey)}`);
    for (const field of section.fields) {
      lines.push(`- ${t(field.labelKey)}: ${autoFieldText(field, fields, trade, excursion, instrumentLabel).replace(/\n/g, " ")}`);
    }
    lines.push("");
  }
  return lines.join("\n");
}

export function autoFieldText(
  field: TemplateField,
  fields: Record<string, string>,
  trade: TradeDetail | null,
  excursion: Excursion | null,
  instrumentLabel: string,
): string {
  if (field.kind !== "auto") {
    const value = fields[field.key] ?? "";
    const choice = field.choices?.find((item) => item.value === value);
    return choice ? t(choice.labelKey) : value;
  }
  switch (field.auto) {
    case "time":
      return trade
        ? `${formatDateTime(trade.openedAtMs)} → ${trade.closedAtMs ? formatDateTime(trade.closedAtMs) : t("trading.open")}`
        : "—";
    case "instrument":
      return trade
        ? `${instrumentLabel} · ${t(trade.direction === "long" ? "trading.long" : "trading.short")}`
        : instrumentLabel;
    case "netResult":
      if (!trade || trade.status !== "closed") return t("trading.auto.afterExit");
      return `${formatSigned(trade.netPnl)}${trade.metrics?.netR ? ` (${trade.metrics.netR}R)` : ` (${t("trading.auto.noR")})`}`;
    case "excursion":
      if (!excursion?.available) return "—";
      return t("trading.auto.excursionValue", {
        mfe: formatPrice(excursion.mfePrice), mae: formatPrice(excursion.maePrice),
        mfePct: excursion.mfePct ?? "—", maePct: excursion.maePct ?? "—", interval: excursion.interval,
      }) + (excursion.mfeR ? ` · ${excursion.mfeR}R / ${excursion.maeR}R` : "");
    case "costs":
      if (!trade) return "—";
      return t("trading.auto.costsValue", {
        fees: formatAmount(trade.fees, 4),
        slippage: trade.metrics?.entrySlippage ? formatSigned(trade.metrics.entrySlippage, 4) : "—",
      });
    default:
      return "—";
  }
}
