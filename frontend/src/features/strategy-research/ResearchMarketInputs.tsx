import { lazy, Suspense, useState } from "react";
import { t } from "../../i18n/index.js";
import { useLocale } from "../../i18n/useLocale.js";
import { getNativeIntervals, useExchangeCatalog } from "../chart-session/exchangeCatalogRuntime.js";
import type { SymbolSelection } from "../symbol-search/useSymbolSearchRuntime.js";
import { marketInputKey, validMarketInput, type ResearchMarketInput } from "./strategyResearchBatch.js";

const SymbolSearchModal = lazy(() => import("../symbol-search/SymbolSearchModal.js"));

export default function ResearchMarketInputs({ markets, limit, onChange }: {
  markets: readonly ResearchMarketInput[];
  limit: number;
  onChange(next: readonly ResearchMarketInput[]): void;
}) {
  const locale = useLocale();
  const [editing, setEditing] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [symbol, setSymbol] = useState<SymbolSelection | null>(null);
  const [interval, setInterval] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const { exchangeCatalog, exchangeCatalogStatus } = useExchangeCatalog(editing);
  const intervals = symbol && exchangeCatalogStatus === "ready"
    ? getNativeIntervals(symbol.exchange, exchangeCatalog, symbol.marketType, "history").filter(item => item.seconds >= 60)
    : [];
  const selectedInterval = intervals.find(item => item.value === interval)?.value ?? intervals[0]?.value ?? "";
  const candidate = symbol && selectedInterval ? {
    session: { exchange: symbol.exchange, marketType: symbol.marketType, symbol: symbol.symbol, interval: selectedInterval },
    startMs: Date.parse(start + "Z"), endMs: Date.parse(end + "Z"),
  } : null;
  const valid = candidate && validMarketInput(candidate);
  function add() {
    if (!candidate || !valid || markets.length >= limit || markets.some(item => marketInputKey(item) === marketInputKey(candidate))) return;
    onChange([...markets, candidate]);
    setEditing(false);
  }
  return <div data-testid="research-market-inputs">
    {markets.length > 0 && <ul>{markets.map(item => {
      const key = marketInputKey(item);
      return <li key={key}>
        {item.session.exchange} · {item.session.marketType} · {item.session.symbol} · {item.session.interval}
        <p>{new Date(item.startMs).toLocaleString(locale)} – {new Date(item.endMs).toLocaleString(locale)}</p>
        <button type="button" onClick={() => onChange(markets.filter(value => marketInputKey(value) !== key))}>{t("indicator.remove")}</button>
      </li>;
    })}</ul>}
    {!editing && <button type="button" disabled={markets.length >= limit} onClick={() => setEditing(true)}>{t("researchBatch.marketAdd")}</button>}
    {editing && <fieldset>
      <legend>{t("researchBatch.marketAdd")}</legend>
      <button type="button" onClick={() => setSearchOpen(true)}>{symbol ? `${symbol.exchange} · ${symbol.marketType} · ${symbol.symbol}` : t("researchBatch.marketSymbol")}</button>
      {searchOpen && <Suspense fallback={<p role="status">{t("research.loading")}</p>}>
        <SymbolSearchModal open={searchOpen} onClose={() => setSearchOpen(false)}
          currentSymbol={symbol?.symbol ?? ""} currentExchange={symbol?.exchange ?? "binance"}
          currentMarketType={symbol?.marketType ?? null} exchangeCatalog={exchangeCatalog}
          onSelect={value => { setSymbol(value); setInterval(""); }} />
      </Suspense>}
      {symbol && <label>{t("researchBatch.marketInterval")}
        <select value={selectedInterval} onChange={event => setInterval(event.target.value)}>
          {intervals.map(item => <option key={item.value} value={item.value}>{item.value}</option>)}
        </select>
      </label>}
      {symbol && !intervals.length && <p role="status">{t("researchBatch.marketUnavailable")}</p>}
      <label>{t("researchBatch.marketStart")} <input type="datetime-local" value={start} onChange={event => setStart(event.target.value)} /></label>
      <label>{t("researchBatch.marketEnd")} <input type="datetime-local" value={end} onChange={event => setEnd(event.target.value)} /></label>
      {start && end && !valid && <p role="status">{t("researchBatch.marketRange")}</p>}
      <button type="button" onClick={add} disabled={!valid || markets.length >= limit
        || markets.some(item => candidate && marketInputKey(item) === marketInputKey(candidate))}>{t("researchBatch.marketSave")}</button>
      <button type="button" onClick={() => { setEditing(false); setSearchOpen(false); }}>{t("backtest.close")}</button>
    </fieldset>}
  </div>;
}
