import { t } from "../../i18n/index.js";
import { TRADE_REVIEW_TEMPLATE, type TemplateField } from "./journalTemplates.js";
import { formatAmount, formatDateTime, formatPrice, formatSigned } from "./tradingFormat.js";
import type { Excursion, TradeDetail } from "./tradingTypes.js";

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
