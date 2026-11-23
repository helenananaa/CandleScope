import { useState } from "react";
import { Button, Field, InlineAlert, Input, SegmentedControl } from "../../components/ui/index.js";
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
      <SegmentedControl
        className="trading-side"
        size="sm"
        fullWidth
        label={t("trading.ticket.side")}
        value={side}
        onChange={setSide}
        options={[{ value: "buy", label: t("trading.ticket.buy") }, { value: "sell", label: t("trading.ticket.sell") }]}
      />
      <div className="trading-field-row">
        <Field label={t("trading.manual.qty")}>
          <Input size="sm" inputMode="decimal" value={qty} onChange={(event) => setQty(event.target.value)} />
        </Field>
        <Field label={t("trading.manual.price")}>
          <Input size="sm" inputMode="decimal" value={price} onChange={(event) => setPrice(event.target.value)} />
        </Field>
      </div>
      <div className="trading-field-row trading-field-row-wrap">
        <Field label={t("trading.manual.fee")}>
          <Input size="sm" inputMode="decimal" value={fee} placeholder="0" onChange={(event) => setFee(event.target.value)} />
        </Field>
        <Field label={t("trading.manual.time")}>
          <Input size="sm" type="datetime-local" value={time} onChange={(event) => setTime(event.target.value)} />
        </Field>
      </div>
      {error && <InlineAlert tone="danger">{error}</InlineAlert>}
      <div className="trading-actions">
        <Button size="sm" variant="primary" disabled={busy || !qty || !price} onClick={() => { void submit(); }}>
          {t("trading.manual.add")}
        </Button>
      </div>
    </section>
  );
}
