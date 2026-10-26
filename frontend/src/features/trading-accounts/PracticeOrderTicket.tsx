import { useMemo, useState } from "react";
import { t } from "../../i18n/index.js";
import { useLocale } from "../../i18n/useLocale.js";
import { tradingApi } from "./tradingApi.js";
import { formatAmount, formatPrice } from "./tradingFormat.js";
import type { AccountSummary, TradingAccount, TradingChartContext } from "./tradingTypes.js";
import { tradingErrorMessage } from "./useTradingAccountsRuntime.js";

type OrderType = "market" | "limit" | "stop";

export interface PlanDraft {
  entryPrice: string;
  stopPrice: string;
  targetPrice: string;
  riskUsdt: string;
}

export default function PracticeOrderTicket({
  account,
  summary,
  context,
  onPlaced,
  onPlanTrade,
}: {
  account: TradingAccount;
  summary: AccountSummary | null;
  context: TradingChartContext;
  onPlaced(): void;
  onPlanTrade(draft: PlanDraft): void;
}) {
  useLocale();
  const [side, setSide] = useState<"buy" | "sell">("buy");
  const [type, setType] = useState<OrderType>("market");
  const [qty, setQty] = useState("");
  const [price, setPrice] = useState("");
  const [stopLoss, setStopLoss] = useState("");
  const [takeProfit, setTakeProfit] = useState("");
  const [reduceOnly, setReduceOnly] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ tone: "error" | "ok"; text: string } | null>(null);

  const reference = context.lastPrice;
  const entry = type === "market" ? reference : Number(price) || null;
  const risk = useMemo(() => {
    const quantity = Number(qty);
    const stop = Number(stopLoss);
    if (!entry || !Number.isFinite(quantity) || quantity <= 0 || !Number.isFinite(stop) || stop <= 0) return null;
    return Math.abs(entry - stop) * quantity;
  }, [entry, qty, stopLoss]);
  const equity = summary ? Number(summary.equity) : null;
  const notional = entry && Number(qty) > 0 ? entry * Number(qty) : null;

  const submit = async () => {
    setBusy(true);
    setMessage(null);
    try {
      const response = await tradingApi.placeOrder(account.id, {
        exchange: context.exchange,
        marketType: context.marketType,
        symbol: context.symbol,
        side,
        type,
        qty,
        ...(type === "limit" ? { limitPrice: price } : {}),
        ...(type === "stop" ? { stopPrice: price } : {}),
        ...(!reduceOnly && stopLoss ? { bracketStop: stopLoss } : {}),
        ...(!reduceOnly && takeProfit ? { bracketTarget: takeProfit } : {}),
        reduceOnly,
        ...(reference ? { referencePrice: String(reference) } : {}),
      });
      setMessage({
        tone: "ok",
        text: response.order.status === "filled"
          ? t("trading.ticket.filled", { price: formatPrice(response.order.fillPrice) })
          : t("trading.ticket.working"),
      });
      onPlaced();
    } catch (cause) {
      setMessage({ tone: "error", text: tradingErrorMessage(cause) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="trading-ticket" aria-label={t("trading.ticket.title")}>
      <div className="trading-segmented" role="group" aria-label={t("trading.ticket.side")}>
        <button type="button" data-active={side === "buy"} data-tone="up" onClick={() => setSide("buy")}>
          {t(context.marketType === "futures" ? "trading.ticket.long" : "trading.ticket.buy")}
        </button>
        <button type="button" data-active={side === "sell"} data-tone="down" onClick={() => setSide("sell")}>
          {t(context.marketType === "futures" ? "trading.ticket.short" : "trading.ticket.sell")}
        </button>
      </div>
      <div className="trading-segmented" role="group" aria-label={t("trading.ticket.type")}>
        {(["market", "limit", "stop"] as const).map((item) => (
          <button key={item} type="button" data-active={type === item} onClick={() => setType(item)}>
            {t(`trading.ticket.${item}` as const)}
          </button>
        ))}
      </div>
      <div className="trading-field-row">
        <label className="trading-field">
          <span>{t("trading.ticket.qty", { base: context.symbol.replace(/USDT$|USDC$|USD$/, "") || context.symbol })}</span>
          <input inputMode="decimal" value={qty} onChange={(event) => setQty(event.target.value)} />
        </label>
        {type !== "market" && (
          <label className="trading-field">
            <span>{t(type === "limit" ? "trading.ticket.limitPrice" : "trading.ticket.stopPrice")}</span>
            <input inputMode="decimal" value={price} placeholder={reference ? String(reference) : ""} onChange={(event) => setPrice(event.target.value)} />
          </label>
        )}
      </div>
      {!reduceOnly && (
        <div className="trading-field-row">
          <label className="trading-field">
            <span>{t("trading.ticket.stopLoss")}</span>
            <input inputMode="decimal" value={stopLoss} onChange={(event) => setStopLoss(event.target.value)} />
          </label>
          <label className="trading-field">
            <span>{t("trading.ticket.takeProfit")}</span>
            <input inputMode="decimal" value={takeProfit} onChange={(event) => setTakeProfit(event.target.value)} />
          </label>
        </div>
      )}
      <label className="trading-check">
        <input type="checkbox" checked={reduceOnly} onChange={(event) => setReduceOnly(event.target.checked)} />
        <span>{t("trading.ticket.reduceOnly")}</span>
      </label>
      <dl className="trading-kv">
        <dt>{t("trading.ticket.reference")}</dt>
        <dd>{reference ? formatPrice(reference) : t("trading.ticket.noPrice")}</dd>
        <dt>{t("trading.ticket.notional")}</dt>
        <dd>{notional ? formatAmount(notional) : "—"}</dd>
        <dt>{t("trading.ticket.risk")}</dt>
        <dd>
          {risk === null ? "—" : formatAmount(risk)}
          {risk !== null && equity ? ` · ${formatAmount((risk / equity) * 100)}%` : ""}
        </dd>
      </dl>
      {message && (
        <p className={message.tone === "error" ? "trading-error" : "trading-ok"} role={message.tone === "error" ? "alert" : "status"}>
          {message.text}
        </p>
      )}
      <div className="trading-actions">
        <button
          type="button"
          className="trading-button"
          disabled={!entry}
          onClick={() => onPlanTrade({
            entryPrice: entry ? String(entry) : "",
            stopPrice: stopLoss,
            targetPrice: takeProfit,
            riskUsdt: risk === null ? "" : risk.toFixed(2),
          })}
        >
          {t("trading.ticket.plan")}
        </button>
        <button
          type="button"
          className="trading-button"
          data-variant={side === "buy" ? "buy" : "sell"}
          disabled={busy || !qty || account.archived}
          onClick={() => { void submit(); }}
        >
          {t(side === "buy" ? "trading.ticket.submitBuy" : "trading.ticket.submitSell")}
        </button>
      </div>
      <p className="trading-help">{t("trading.ticket.model")}</p>
    </section>
  );
}
