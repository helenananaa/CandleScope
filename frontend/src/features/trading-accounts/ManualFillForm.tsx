import { useState } from "react";
import { t } from "../../i18n/index.js";
import { useLocale } from "../../i18n/useLocale.js";
import { tradingApi } from "./tradingApi.js";
import type { TradingAccount, TradingChartContext } from "./tradingTypes.js";
import { tradingErrorMessage } from "./useTradingAccountsRuntime.js";

function localInputValue(ms: number): string {
  const date = new Date(ms);
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

export default function ManualFillForm({
  account,
  context,
  onAdded,
}: {
  account: TradingAccount;
  context: TradingChartContext;
  onAdded(): void;
}) {
  useLocale();
  const [side, setSide] = useState<"buy" | "sell">("buy");
  const [qty, setQty] = useState("");
  const [price, setPrice] = useState(context.lastPrice ? String(context.lastPrice) : "");
  const [fee, setFee] = useState("");
  const [time, setTime] = useState(() => localInputValue(Date.now()));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const tsMs = new Date(time).getTime();
      await tradingApi.addFill(account.id, {
        exchange: context.exchange,
        marketType: context.marketType,
        symbol: context.symbol,
        side,
        qty,
        price,
        ...(fee ? { fee } : {}),
        ...(Number.isFinite(tsMs) ? { tsMs } : {}),
      });
      setQty("");
      setFee("");
      onAdded();
    } catch (cause) {
      setError(tradingErrorMessage(cause));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="trading-ticket" aria-label={t("trading.manual.title")}>
      <p className="trading-help">{t("trading.manual.help", { symbol: context.symbol })}</p>
      <div className="trading-segmented" role="group" aria-label={t("trading.ticket.side")}>
        <button type="button" data-active={side === "buy"} data-tone="up" onClick={() => setSide("buy")}>{t("trading.ticket.buy")}</button>
        <button type="button" data-active={side === "sell"} data-tone="down" onClick={() => setSide("sell")}>{t("trading.ticket.sell")}</button>
      </div>
      <div className="trading-field-row">
        <label className="trading-field">
          <span>{t("trading.manual.qty")}</span>
          <input inputMode="decimal" value={qty} onChange={(event) => setQty(event.target.value)} />
        </label>
        <label className="trading-field">
          <span>{t("trading.manual.price")}</span>
          <input inputMode="decimal" value={price} onChange={(event) => setPrice(event.target.value)} />
        </label>
      </div>
      <div className="trading-field-row">
        <label className="trading-field">
          <span>{t("trading.manual.fee")}</span>
          <input inputMode="decimal" value={fee} placeholder="0" onChange={(event) => setFee(event.target.value)} />
        </label>
        <label className="trading-field">
          <span>{t("trading.manual.time")}</span>
          <input type="datetime-local" value={time} onChange={(event) => setTime(event.target.value)} />
        </label>
      </div>
      {error && <p className="trading-error" role="alert">{error}</p>}
      <div className="trading-actions">
        <button type="button" className="trading-button" data-variant="primary" disabled={busy || !qty || !price} onClick={() => { void submit(); }}>
          {t("trading.manual.add")}
        </button>
      </div>
    </section>
  );
}
