import { useEffect, useId, useState } from "react";
import { Field, Input, Select } from "../../components/ui/index.js";
import { useLocale } from "../../i18n/useLocale.js";

export interface ReplayVenue {
  id: string;
  name: string;
  markets: string[];
  trades: string[];
}
type Market = { exchange: string; marketType: string; symbol: string };
export function useReplayVenues(enabled: boolean) {
  const [venues, setVenues] = useState<ReplayVenue[]>([]);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!enabled) return;
    const abort = new AbortController();
    fetch("/api/v1/local/downloads/markets", { signal: abort.signal })
      .then(async (response) => {
        if (!response.ok) throw Error(String(response.status));
        setVenues(await response.json());
        setError("");
      })
      .catch((error) => {
        if (!abort.signal.aborted) setError(String(error));
      });
    return () => abort.abort();
  }, [enabled]);
  return { venues, error };
}

export function BrowserReplayMarket({
  venues,
  market,
  onChange,
  busy,
  local = [],
}: {
  venues: ReplayVenue[];
  market: Market;
  onChange: (next: Market, quote?: string) => void;
  busy: boolean;
  local?: Market[];
}) {
  const zh = useLocale().startsWith("zh");
  const list = useId();
  const [focused, setFocused] = useState(false);
  const [symbols, setSymbols] = useState<Array<{ symbol: string; quoteAsset: string }>>([]);
  const [unavailable, setUnavailable] = useState(false);
  const { exchange, marketType, symbol } = market;
  const venue = venues.find((v) => v.id === exchange);
  const imported = marketType === "local_bar";
  useEffect(() => {
    setSymbols([]);
    setUnavailable(false);
    if (!focused || imported || !exchange) return;
    const abort = new AbortController();
    const timer = setTimeout(async () => {
      try {
        const query = new URLSearchParams({ exchange, market_type: marketType, search: symbol });
        const res = await fetch("/api/v1/symbols/exchange-info?" + query, { signal: abort.signal });
        if (!res.ok) throw Error(String(res.status));
        const data = await res.json();
        if (!abort.signal.aborted) setSymbols(data.symbols.slice(0, 80));
      } catch {
        if (!abort.signal.aborted) setUnavailable(true);
      }
    }, 300);
    return () => {
      clearTimeout(timer);
      abort.abort();
    };
  }, [exchange, marketType, symbol, focused, imported]);
  function marketLabel(type: string) {
    if (type === "spot") return zh ? "现货" : "Spot";
    if (type === "local_bar") return zh ? "本地资料" : "Library";
    return type === "swap" ? (zh ? "永续" : "Perpetual") : zh ? "线性永续" : "Linear perpetual";
  }
  return (
    <>
      <Field label={zh ? "交易所" : "Exchange"}>
        <Select
          disabled={busy}
          value={exchange}
          onChange={(e) => {
            const id = e.target.value,
              selected = venues.find((v) => v.id === id);
            const entry = local.find((m) => m.exchange === id);
            if (selected)
              onChange({
                exchange: id,
                marketType: selected.markets.includes(marketType) ? marketType : selected.markets[0]!,
                symbol: "",
              });
            else if (entry) onChange(entry);
          }}
        >
          {!venues.some((v) => v.id === exchange) && !local.some((m) => m.exchange === exchange) && (
            <option value={exchange}>{exchange}</option>
          )}
          {venues.map((v) => (
            <option key={v.id} value={v.id}>
              {v.name}
            </option>
          ))}
          {local.map((m) => (
            <option key={m.exchange} value={m.exchange}>
              {m.symbol} · {m.exchange}
            </option>
          ))}
        </Select>
      </Field>
      <Field label={zh ? "市场类型" : "Market type"}>
        <Select
          disabled={busy || imported}
          value={marketType}
          onChange={(e) => onChange({ exchange, marketType: e.target.value, symbol: "" })}
        >
          {(venue?.markets.includes(marketType)
            ? venue.markets
            : [marketType, ...(venue?.markets ?? [])]
          ).map((m) => (
            <option key={m} value={m}>
              {marketLabel(m)}
            </option>
          ))}
        </Select>
      </Field>
      <Field label={zh ? "商品" : "Symbol"}>
        <Input
          name="symbol"
          required
          value={symbol}
          disabled={busy || imported}
          list={list}
          autoComplete="off"
          onFocus={() => setFocused(true)}
          onBlur={() => setFocused(false)}
          onChange={(e) => {
            const next = e.target.value.trim().toUpperCase();
            onChange(
              { ...market, symbol: next },
              symbols.find((s) => s.symbol.toUpperCase() === next)?.quoteAsset,
            );
          }}
        />
      </Field>
      <datalist id={list}>
        {symbols.map((s) => (
          <option key={s.symbol} value={s.symbol} />
        ))}
      </datalist>
      {unavailable && (
        <small>
          {zh
            ? "暂时无法读取品种目录，可输入交易所的完整品种代码。"
            : "Symbol lookup unavailable. Enter the full market symbol."}
        </small>
      )}
    </>
  );
}
