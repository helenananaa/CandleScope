import { lazy, Suspense, useState } from "react";
import { Button, Field, Input, Select } from "../../components/ui/index.js";
import { t } from "../../i18n/index.js";
import { useLocale } from "../../i18n/useLocale.js";
import { getNativeIntervals, useExchangeCatalog } from "../chart-session/exchangeCatalogRuntime.js";
import type { SymbolSelection } from "../symbol-search/useSymbolSearchRuntime.js";
import { marketInputKey, validMarketInput, type ResearchMarketInput } from "./strategyResearchBatch.js";

const SymbolSearchModal = lazy(() => import("../symbol-search/SymbolSearchModal.js"));

function utcInputValue(ms: number | undefined): string {
  return ms === undefined ? "" : new Date(ms).toISOString().slice(0, 16);
}

/**
 * One exchange history input: a market symbol, a historical interval and a past range `[start, end)`.
 * Used for batch inputs and for the research workspace's own data source (ADR-BACKTEST-015 P5a).
 */
export function ResearchMarketInputForm({ legend, submitLabel, initial = null, disabled = false, onSave, onCancel }: {
  legend: string;
  submitLabel: string;
  initial?: ResearchMarketInput | null;
  /** The input is already taken (a batch holds it): it cannot be saved again. */
  disabled?: boolean | ((input: ResearchMarketInput) => boolean);
  onSave(input: ResearchMarketInput): void;
  onCancel?(): void;
}) {
  const [searchOpen, setSearchOpen] = useState(false);
  const [symbol, setSymbol] = useState<SymbolSelection | null>(() => initial
    ? { exchange: initial.session.exchange, marketType: initial.session.marketType, symbol: initial.session.symbol } as SymbolSelection
    : null);
  const [interval, setInterval] = useState(initial?.session.interval ?? "");
  const [start, setStart] = useState(() => utcInputValue(initial?.startMs));
  const [end, setEnd] = useState(() => utcInputValue(initial?.endMs));
  const { exchangeCatalog, exchangeCatalogStatus } = useExchangeCatalog(true);
  const intervals = symbol && exchangeCatalogStatus === "ready"
    ? getNativeIntervals(symbol.exchange, exchangeCatalog, symbol.marketType, "history").filter(item => item.seconds >= 60)
    : [];
  const selectedInterval = intervals.find(item => item.value === interval)?.value ?? intervals[0]?.value ?? "";
  const candidate: ResearchMarketInput | null = symbol && selectedInterval ? {
    session: { exchange: symbol.exchange, marketType: symbol.marketType, symbol: symbol.symbol, interval: selectedInterval },
    startMs: Date.parse(start + "Z"), endMs: Date.parse(end + "Z"),
  } : null;
  const valid = candidate !== null && validMarketInput(candidate);
  const taken = candidate !== null && (typeof disabled === "function" ? disabled(candidate) : disabled);
  return <fieldset className="strategy-research-market-form" data-testid="research-market-form">
    <legend>{legend}</legend>
    <Button size="sm" onClick={() => setSearchOpen(true)}>{symbol ? `${symbol.exchange} · ${symbol.marketType} · ${symbol.symbol}` : t("researchBatch.marketSymbol")}</Button>
    {searchOpen && <Suspense fallback={<p className="strategy-research-note" role="status">{t("research.loading")}</p>}>
      <SymbolSearchModal open={searchOpen} onClose={() => setSearchOpen(false)}
        currentSymbol={symbol?.symbol ?? ""} currentExchange={symbol?.exchange ?? "binance"}
        currentMarketType={symbol?.marketType ?? null} exchangeCatalog={exchangeCatalog}
        onSelect={value => { setSymbol(value); setInterval(""); }} />
    </Suspense>}
    {symbol && <Field label={t("researchBatch.marketInterval")}>
      <Select size="sm" value={selectedInterval} onChange={event => setInterval(event.target.value)}>
        {intervals.map(item => <option key={item.value} value={item.value}>{item.value}</option>)}
      </Select>
    </Field>}
    {symbol && exchangeCatalogStatus === "ready" && !intervals.length && <p className="strategy-research-note" role="status">{t("researchBatch.marketUnavailable")}</p>}
    <Field label={t("researchBatch.marketStart")}><Input size="sm" type="datetime-local" value={start} onChange={event => setStart(event.target.value)} /></Field>
    <Field label={t("researchBatch.marketEnd")}><Input size="sm" type="datetime-local" value={end} onChange={event => setEnd(event.target.value)} /></Field>
    {start && end && !valid && <p className="strategy-research-note" role="status">{t("researchBatch.marketRange")}</p>}
    <div className="strategy-history-actions">
      <Button size="sm" variant="primary" disabled={!valid || taken}
        onClick={() => { if (candidate && valid && !taken) onSave(candidate); }}>{submitLabel}</Button>
      {onCancel && <Button size="sm" variant="ghost" onClick={() => { setSearchOpen(false); onCancel(); }}>{t("backtest.close")}</Button>}
    </div>
  </fieldset>;
}

export default function ResearchMarketInputs({ markets, limit, onChange }: {
  markets: readonly ResearchMarketInput[];
  limit: number;
  onChange(next: readonly ResearchMarketInput[]): void;
}) {
  const locale = useLocale();
  const [editing, setEditing] = useState(false);
  return <div className="strategy-research-markets" data-testid="research-market-inputs">
    {markets.length > 0 && <ul className="strategy-history-list">{markets.map(item => {
      const key = marketInputKey(item);
      return <li key={key} className="strategy-history-row">
        <div className="strategy-history-run">
          <strong>{item.session.exchange} · {item.session.marketType} · {item.session.symbol} · {item.session.interval}</strong>
          <span>{new Date(item.startMs).toLocaleString(locale)} – {new Date(item.endMs).toLocaleString(locale)}</span>
        </div>
        <Button size="sm" variant="ghost" onClick={() => onChange(markets.filter(value => marketInputKey(value) !== key))}>{t("indicator.remove")}</Button>
      </li>;
    })}</ul>}
    {!editing && <Button size="sm" disabled={markets.length >= limit} onClick={() => setEditing(true)}>{t("researchBatch.marketAdd")}</Button>}
    {editing && <ResearchMarketInputForm legend={t("researchBatch.marketAdd")} submitLabel={t("researchBatch.marketSave")}
      disabled={(candidate) => markets.length >= limit || markets.some(item => marketInputKey(item) === marketInputKey(candidate))}
      onSave={(candidate) => { onChange([...markets, candidate]); setEditing(false); }}
      onCancel={() => setEditing(false)} />}
  </div>;
}
