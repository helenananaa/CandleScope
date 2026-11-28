import { useMemo, useState } from "react";
import { Button, Checkbox, Field, InlineAlert, Input, SegmentedControl } from "../../components/ui/index.js";
import { t } from "../../i18n/index.js";
import { useLocale } from "../../i18n/useLocale.js";
import { chartInstrumentFields } from "./chartInstrument.js";
import { usePracticeMarketRules } from "./practiceMarketRules.js";
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
  const [oneWaySide, setSide] = useState<"buy" | "sell">("buy");
  const [type, setType] = useState<OrderType>("market");
  const [qty, setQty] = useState("");
  const [price, setPrice] = useState("");
  const [stopLoss, setStopLoss] = useState("");
  const [takeProfit, setTakeProfit] = useState("");
  const [oneWayReduceOnly, setReduceOnly] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ tone: "error" | "ok"; text: string } | null>(null);

  // The market's account model decides shorting and hedge intent (ADR-DATA-002 D5b).
  const rules = usePracticeMarketRules(context);
  const hedge = account.settings.positionMode === "HEDGE" && rules.hedge;
  const [action, setAction] = useState<"openLong" | "openShort" | "closeLong" | "closeShort">("openLong");
  const positionSide = action === "openLong" || action === "closeLong" ? "LONG" : "SHORT";
  const reduceOnly = hedge ? action === "closeLong" || action === "closeShort" : oneWayReduceOnly;
  const side = hedge ? (action === "openLong" || action === "closeShort" ? "buy" : "sell") : oneWaySide;
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
        ...chartInstrumentFields(context),
        side,
        ...(hedge ? { positionSide, positionEffect: reduceOnly ? "close" : "open" } : {}),
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
          : t(response.waitsForOpen ? "trading.ticket.waitsForOpen" : "trading.ticket.working"),
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
      {hedge ? <SegmentedControl size="sm" fullWidth label={t("trading.ticket.side")} value={action} onChange={setAction}
        options={(["openLong", "openShort", "closeLong", "closeShort"] as const).map(value => ({
          value, label: t(`backtest.${value}` as const),
        }))} /> : <SegmentedControl
        className="trading-side"
        size="sm"
        fullWidth
        label={t("trading.ticket.side")}
        value={side}
        onChange={setSide}
        options={[
          { value: "buy", label: t(rules.shorting ? "trading.ticket.long" : "trading.ticket.buy") },
          { value: "sell", label: t(rules.shorting ? "trading.ticket.short" : "trading.ticket.sell") },
        ]}
      />}
      <SegmentedControl
        size="sm"
        fullWidth
        label={t("trading.ticket.type")}
        value={type}
        onChange={setType}
        options={(["market", "limit", "stop"] as const).map((item) => ({ value: item, label: t(`trading.ticket.${item}` as const) }))}
      />
      <div className="trading-field-row">
        <Field label={t("trading.ticket.qty", { base: context.symbol.replace(/USDT$|USDC$|USD$/, "") || context.symbol })}>
          <Input size="sm" inputMode="decimal" value={qty} onChange={(event) => setQty(event.target.value)} />
        </Field>
        {type !== "market" && (
          <Field label={t(type === "limit" ? "trading.ticket.limitPrice" : "trading.ticket.stopPrice")}>
            <Input size="sm" inputMode="decimal" value={price} placeholder={reference ? String(reference) : ""} onChange={(event) => setPrice(event.target.value)} />
          </Field>
        )}
      </div>
      {!reduceOnly && (
        <div className="trading-field-row">
          <Field label={t("trading.ticket.stopLoss")}>
            <Input size="sm" inputMode="decimal" value={stopLoss} onChange={(event) => setStopLoss(event.target.value)} />
          </Field>
          <Field label={t("trading.ticket.takeProfit")}>
            <Input size="sm" inputMode="decimal" value={takeProfit} onChange={(event) => setTakeProfit(event.target.value)} />
          </Field>
        </div>
      )}
      {!hedge && <Checkbox label={t("trading.ticket.reduceOnly")} checked={reduceOnly} onChange={(event) => setReduceOnly(event.target.checked)} />}
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
      {!rules.opensPositions && <InlineAlert tone="warning">{t("trading.ticket.modelUnsupported")}</InlineAlert>}
      {message && <InlineAlert tone={message.tone === "error" ? "danger" : "success"}>{message.text}</InlineAlert>}
      <div className="trading-actions">
        <Button
          size="sm"
          disabled={!entry}
          onClick={() => onPlanTrade({
            entryPrice: entry ? String(entry) : "",
            stopPrice: stopLoss,
            targetPrice: takeProfit,
            riskUsdt: risk === null ? "" : risk.toFixed(2),
          })}
        >
          {t("trading.ticket.plan")}
        </Button>
        <Button
          size="sm"
          variant="primary"
          className="trading-submit"
          data-side={side}
          disabled={busy || !qty || account.archived}
          onClick={() => { void submit(); }}
        >
          {hedge ? t(`backtest.${action}` as const) : t(side === "buy" ? "trading.ticket.submitBuy" : "trading.ticket.submitSell")}
        </Button>
      </div>
      <p className="trading-help">{t("trading.ticket.model")}</p>
    </section>
  );
}
