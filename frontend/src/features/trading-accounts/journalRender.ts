import { t } from "../../i18n/index.js";
import { TRADE_REVIEW_TEMPLATE, type TemplateField } from "./journalTemplates.js";
import { formatAmount, formatDateTime, formatPrice, formatSigned } from "./tradingFormat.js";
import type { Excursion, LinkSuggestion, TradeDetail } from "./tradingTypes.js";

/** Plans saved in the same minute share a time, so add what was planned; empty parts are left out. */
export function linkSuggestionLabel(item: LinkSuggestion): string {
  const parts = [t("trading.journal.linkPlan", { time: formatDateTime(item.createdAtMs) })];
  if (item.direction) parts.push(t(item.direction === "long" ? "trading.long" : "trading.short"));
  if (item.entryPrice !== null) parts.push(t("trading.journal.suggestion.entry", { value: formatPrice(item.entryPrice) }));
  if (item.stopPrice !== null) parts.push(t("trading.journal.suggestion.stop", { value: formatPrice(item.stopPrice) }));
  if (item.targetPrice !== null) parts.push(t("trading.journal.suggestion.target", { value: formatPrice(item.targetPrice) }));
  if (item.riskUsdt !== null) parts.push(t("trading.journal.suggestion.risk", { value: formatAmount(item.riskUsdt) }));
  return parts.join(" · ");
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
