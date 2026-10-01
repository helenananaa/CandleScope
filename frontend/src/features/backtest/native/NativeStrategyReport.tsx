import { strategyTradeFocus, type StrategyTradeFocus } from "../chart-tester/strategyTradeReview.js";
import { useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { t } from "../../../i18n/index.js";
import { useLocale } from "../../../i18n/useLocale.js";
import { nativeExportUrl, type NativeRun } from "./nativeBacktestApi.js";
import { NativeReplayControls, type NativeReplayRecord } from "./NativeReplayControls.js";
import { NativeDrawingScene } from "./NativeDrawingScene.js";
import { NativeSeriesScene } from "./NativeSeriesScene.js";

interface NativeMarker { time: number; value: number; kind: "entry" | "exit" | "fill" }
export function NativeCurve({ points, title, markers = [], onLocate }: { points: Array<{ time: number; value: number | null }>; title: string;
  markers?: NativeMarker[]; onLocate?: ((time: number) => void) | undefined }) {
  const locale = useLocale();
  const [selected, setSelected] = useState<number | null>(null);
  const finite = points.filter((point) => point.value !== null && Number.isFinite(point.value));
  if (!finite.length) return null;
  let min = Infinity, max = -Infinity;
  for (const point of finite) { min = Math.min(min, point.value!); max = Math.max(max, point.value!); }
  for (const marker of markers) { min = Math.min(min, marker.value); max = Math.max(max, marker.value); }
  const timeIndex = new Map(points.map((point, index) => [point.time, index]));
  const span = max - min || 1;
  const stride = Math.max(1, Math.ceil(points.length / 4000));
  const segments: string[] = [];
  let gap = true;
  for (let index = 0; index < points.length; index += stride) {
    const point = points[index]!;
    if (point.value === null || !Number.isFinite(point.value)) { gap = true; continue; }
    const x = 40 + 920 * index / Math.max(1, points.length - 1);
    const y = 160 - 140 * (point.value - min) / span;
    segments.push(`${gap ? "M" : "L"}${x.toFixed(2)},${y.toFixed(2)}`);
    gap = false;
  }
  const point = selected === null ? null : points[selected];
  return <figure className="native-curve"><figcaption>{title} · {min.toFixed(2)} — {max.toFixed(2)}
    {point && <> · {new Date(point.time * 1000).toLocaleString(locale)} · {point.value ?? "—"}</>}</figcaption>
    <svg viewBox="0 0 1000 180" role="img" aria-label={title} onMouseLeave={() => setSelected(null)}
      onMouseMove={(event) => { const box = event.currentTarget.getBoundingClientRect();
        setSelected(Math.max(0, Math.min(points.length - 1, Math.round(((event.clientX - box.left) / box.width * 1000 - 40) / 920 * (points.length - 1))))); }}>
      <path d={segments.join(" ")} fill="none" stroke="var(--accent, #38bdf8)" strokeWidth="2" />
      {markers.map((marker, index) => {
        const bar = timeIndex.get(marker.time);
        if (bar === undefined) return null;
        return <circle key={index} cx={40 + bar / Math.max(1, points.length - 1) * 920} cy={160 - 140 * (marker.value - min) / span}
          r="4" fill={marker.kind === "entry" ? "#22c55e" : "#fb7185"} onClick={() => onLocate?.(marker.time * 1000)}>
          <title>{`${t(marker.kind === "entry" ? "native.entry" : marker.kind === "exit" ? "native.exit" : "native.external.fill")} · ${new Date(marker.time * 1000).toLocaleString(locale)} · ${marker.value}`}</title>
        </circle>;
      })}
      {selected !== null && <line x1={40 + selected / Math.max(1, points.length - 1) * 920} x2={40 + selected / Math.max(1, points.length - 1) * 920} y1="10" y2="170" stroke="currentColor" opacity="0.4" />}
    </svg></figure>;
}

export function NativeStrategyReport({ run, onLocate, onReviewTrade, active = true, view = "all" }: { active?: boolean; onReviewTrade?: ((trade: StrategyTradeFocus | null) => void) | undefined; view?: "all" | "overview" | "trades"; run: NativeRun; onLocate?: ((time: number) => void) | undefined }) {
  const [replay, setReplay] = useState<NativeReplayRecord | null>(null);
  return <NativeResultBody key={replay?.replay_id ?? run.run_id} run={replay ? { ...run, result: replay.result } : run} onLocate={onLocate} view={view} onReviewTrade={onReviewTrade} active={active}
      controls={run.execution_mode !== "CANDLESCOPE" ? <NativeReplayControls runId={run.run_id} replay={replay} onChange={setReplay} /> : null}
      exportUrl={replay ? nativeExportUrl(run.run_id).replace(`/runs/${run.run_id}/`, `/replays/${replay.replay_id}/`) : nativeExportUrl(run.run_id, run.execution_mode)} />
}

function NativeResultBody({ run, onLocate, exportUrl, view, controls, onReviewTrade, active }: { active: boolean; onReviewTrade: ((trade: StrategyTradeFocus | null) => void) | undefined; controls: ReactNode; view: "all" | "overview" | "trades"; run: NativeRun; onLocate?: ((time: number) => void) | undefined; exportUrl: string }) {
  const locale = useLocale();
  const [section, setSection] = useState<"trades" | "orders">("trades");
  const [positions, setPositions] = useState<Record<"trades" | "orders", { page: number; selectedIndex: number | null }>>({
    trades: { page: 0, selectedIndex: null }, orders: { page: 0, selectedIndex: null },
  });
  const { page, selectedIndex } = positions[section];
  const setPage = (next: number) => setPositions((current) => ({ ...current, [section]: { ...current[section], page: next } }));
  const scrollPositions = useRef({ trades: 0, orders: 0 });
  const table = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    if (table.current && active && view !== "overview") table.current.scrollTop = scrollPositions.current[section];
  }, [section, active, view]);
  const selectedRow = selectedIndex === null ? undefined : run.result?.[section][selectedIndex];
  const focus = useMemo(() => selectedRow ? strategyTradeFocus(selectedRow, `${run.run_id}:${section}:${selectedIndex}`) : null, [selectedRow, run.run_id, section, selectedIndex]);
  useEffect(() => {
    if (!active) return;
    onReviewTrade?.(focus);
    return () => onReviewTrade?.(null);
  }, [active, focus, onReviewTrade]);
  const selectRow = (index: number, focusRow = false) => {
    if (!run.result?.[section][index]) return;
    setPositions((current) => ({ ...current, [section]: { selectedIndex: index, page: Math.floor(index / 50) } }));
    if (!onReviewTrade) {
      const row = run.result?.[section][index];
      const target = row ? strategyTradeFocus(row, String(index)) : null;
      if (target) onLocate?.(target.entryTimeMs);
    }
    requestAnimationFrame(() => {
      const row = table.current?.querySelector<HTMLElement>('[data-selected="true"]');
      row?.scrollIntoView({ block: "nearest" });
      if (focusRow) row?.focus({ preventScroll: true });
    });
  };
  const result = run.result;
  if (!result) return null;
  const samples = result.equity.filter((point) => Number.isFinite(point.value));
  let peak = samples[0]?.value ?? 0;
  let drawdown = 0;
  for (const point of samples) {
    peak = Math.max(peak, point.value);
    if (peak > 0) drawdown = Math.max(drawdown, (peak - point.value) / peak);
  }
  const lastEquity = samples.at(-1)?.value;
  const number = new Intl.NumberFormat(locale, { maximumFractionDigits: 2 });
  const rows = result[section];
  const sourceColumns = [...new Set(rows.flatMap((row) => Object.keys(row)))].filter((column) => !["entryBarIndex", "exitBarIndex"].includes(column));
  const preferred = ["side", "direction", "entryTime", "entry_time", "entry_time_ms", "entryPrice", "entry_price", "exitTime", "exit_time", "exit_time_ms", "exitPrice", "exit_price", "qty", "quantity", "profit", "net_pnl"];
  const columns = [...preferred.filter((key) => sourceColumns.includes(key)), ...sourceColumns.filter((key) => !preferred.includes(key))];
  const labels: Record<string, string> = {
    side: t("chartTester.result.side"), direction: t("chartTester.result.side"), entry_time_ms: t("backtest.openTime"), exit_time_ms: t("backtest.closeTime"),
    entry_price: t("chartTester.result.entry"), exit_price: t("chartTester.result.exit"), net_pnl: t("strategyDock.pnl"),
    entryTime: t("backtest.openTime"), entry_time: t("backtest.openTime"),
    exitTime: t("backtest.closeTime"), exit_time: t("backtest.closeTime"),
    time: t("trade.time"), event_time_ms: t("trade.time"), price: t("trade.price"),
    qty: t("plugin.live.quantity"), quantity: t("plugin.live.quantity"), profit: t("strategyDock.pnl"),
    entryPrice: `${t("native.entry")} · ${t("trade.price")}`, exitPrice: `${t("native.exit")} · ${t("trade.price")}`,
  };
  const formatCell = (column: string, value: unknown): string => {
    if (value == null) return "—";
    if (["entryTime", "entry_time", "exitTime", "exit_time", "time", "event_time_ms", "entry_time_ms", "exit_time_ms"].includes(column)) {
      const date = new Date(Number(value) * (column.endsWith("_ms") ? 1 : 1000));
      return Number.isFinite(date.getTime()) ? date.toLocaleString(locale) : String(value);
    }
    if (typeof value === "number") return new Intl.NumberFormat(locale, { maximumFractionDigits: 8 }).format(value);
    return typeof value === "object" ? JSON.stringify(value) : String(value);
  };
  const markers = result.trades.flatMap((trade): NativeMarker[] => {
    if (run.execution_mode === "CANDLESCOPE") {
      const fillTime = Number(trade.event_time_ms) / 1000;
      const bar = [...result.bars].reverse().find((item) => item.time <= fillTime);
      const price = Number(trade.price);
      return bar && Number.isFinite(price) ? [{ time: bar.time, value: price, kind: "fill" }] : [];
    }
    const entry = { time: Number(trade.entryTime ?? trade.entry_time), value: Number(trade.entryPrice ?? trade.entry_price), kind: "entry" as const };
    const exit = { time: Number(trade.exitTime ?? trade.exit_time), value: Number(trade.exitPrice ?? trade.exit_price), kind: "exit" as const };
    return [entry, exit].filter((marker) => Number.isFinite(marker.time) && Number.isFinite(marker.value));
  });
  const graphics = result.graphics.map((plot, index) => {
    const values = Array.isArray(plot.values) ? plot.values : null;
    const data = Array.isArray(plot.data) ? plot.data : null;
    const points = values ? values.map((value, i) => ({ time: result.bars[i]?.time ?? 0, value: typeof value === "number" ? value : null }))
      : data ? data.map((value: { time: number; value?: number }) => ({ time: value.time, value: value.value ?? null })) : [];
    return { title: String(plot.title ?? plot.name ?? `Plot ${index + 1}`), points };
  });
  return <section className="native-report" data-view={view}>
    <div className="native-report-toolbar">
    {controls}
    <details className="native-report-method"><summary>{t("native.mode")}</summary>
    <p><strong>{result.account_authority}</strong> · {run.execution_mode === "CANDLESCOPE" && run.runtime_identity.engine.package} {run.runtime_identity.engine.version} · {result.fill_model}{result.fidelity && <> · {result.fidelity}</>}</p>
    {run.config?.context && <p>{run.config.context.symbol} · {run.config.interval} · {JSON.stringify(run.config.parameters)}</p>}
    <p>{t(run.execution_mode === "CANDLESCOPE" ? "native.external.authority" : "native.authority")}</p>
    {result.fidelity === "BOOK_DEPTH" && <p>{t("native.external.depthHint")}</p>}
    {result.fidelity === "BOOK_SAMPLED" && <p>{t("native.external.sampledHint")}</p>}
    {run.execution_mode === "CANDLESCOPE" && result.raw_output.entry_allocation != null && <p>{t("native.external.allocationHint")}</p>}
    </details>
    <a href={exportUrl} download>{t(run.execution_mode === "CANDLESCOPE" ? "native.external.export" : "native.export")}</a>
    {result.diagnostics.length > 0 && <details className="native-report-diagnostics"><summary>{t("strategyDock.diagnostics")} ({result.diagnostics.length})</summary><pre>{JSON.stringify(result.diagnostics, null, 2)}</pre></details>}
    </div>
    <div hidden={view === "trades"}>
    <div className="native-report-metrics">
      <div><span>{t("chartTester.result.equity")}</span><strong>{lastEquity == null ? "—" : number.format(lastEquity)}</strong></div>
      <div title={t("chartTester.result.drawdownBasis")}><span>{t("chartTester.result.maxDrawdown")}</span><strong>{samples.length < 2 ? "—" : new Intl.NumberFormat(locale, { style: "percent", maximumFractionDigits: 2 }).format(drawdown)}</strong><small>{t("chartTester.result.drawdownBasis")}</small></div>
      <div><span>{t("native.trades")}</span><strong>{number.format(result.trades.length)}</strong></div>
      <div><span>{t("native.orders")}</span><strong>{number.format(result.orders.length)}</strong></div>
    </div>
    <NativeCurve points={result.equity} title={t(run.execution_mode === "CANDLESCOPE" ? "native.external.equity" : "native.equity")} />
    <details open={view === "all"}><summary>{t("native.price")}</summary>
    <NativeCurve points={result.bars.map((bar) => ({ time: bar.time, value: bar.close }))} title={t("native.price")} markers={markers} onLocate={onLocate} />
    {graphics.map((graphic, index) => <NativeCurve key={index} {...graphic} />)}
    <NativeDrawingScene result={result} />
    <NativeSeriesScene result={result} />
    </details>
    </div>
    <div className="native-trade-view" hidden={view === "overview"}>
    <div className="native-trade-controls">
    <div className="native-trade-sections"><button aria-pressed={section === "trades"} onClick={() => setSection("trades")}>{t("native.trades")} ({result.trades.length})</button>
      <button aria-pressed={section === "orders"} onClick={() => setSection("orders")}>{t("native.orders")} ({result.orders.length})</button></div>
    <div className="strategy-trade-navigation" aria-label={t("strategyReview.navigation")}>
      <button disabled={!rows.length || selectedIndex === 0} onClick={() => selectRow(selectedIndex === null ? 0 : selectedIndex - 1)}>{t("strategyReview.previous")}</button>
      <form className="native-trade-jump" onSubmit={(event) => {
        event.preventDefault();
        const value = Number(new FormData(event.currentTarget).get("trade"));
        if (Number.isInteger(value) && value >= 1 && value <= rows.length) selectRow(value - 1);
      }}>
        <input key={`${section}:${selectedIndex}`} name="trade" type="number" min={1} max={rows.length || 1} step={1}
          defaultValue={selectedIndex === null ? "" : selectedIndex + 1} placeholder="—" disabled={!rows.length}
          aria-label={t("strategyReview.jump")} title={t("strategyReview.jump")} />
        <span aria-hidden="true">/ {rows.length}</span>
        <button type="submit" disabled={!rows.length}>{t("strategyReview.go")}</button>
      </form>
      <button disabled={!rows.length || selectedIndex === rows.length - 1} onClick={() => selectRow(selectedIndex === null ? 0 : selectedIndex + 1)}>{t("strategyReview.next")}</button>
    </div>
    <div className="native-trade-pages">
      <button aria-label={t("strategyReview.previousPage")} disabled={page === 0} onClick={() => setPage(page - 1)}>←</button>
      <span>{page + 1} / {Math.max(1, Math.ceil(rows.length / 50))}</span>
      <button aria-label={t("strategyReview.nextPage")} disabled={(page + 1) * 50 >= rows.length} onClick={() => setPage(page + 1)}>→</button>
    </div>
    </div>
    <div className="native-table" ref={table} onScroll={(event) => { if (active && view !== "overview") scrollPositions.current[section] = event.currentTarget.scrollTop; }}><table><thead><tr>{columns.map((column) => <th key={column}>{labels[column] ?? column}</th>)}</tr></thead>
      <tbody>{rows.slice(page * 50, page * 50 + 50).map((row, index) => {
        const absolute = page * 50 + index;
        return <tr key={absolute} tabIndex={0} aria-selected={selectedIndex === absolute} data-selected={selectedIndex === absolute}
          onClick={() => selectRow(absolute)} onKeyDown={(event) => {
            if (event.key === "Enter" || event.key === " ") { event.preventDefault(); selectRow(absolute); }
            if (event.key === "ArrowUp" || event.key === "ArrowDown") { event.preventDefault(); selectRow(Math.max(0, Math.min(rows.length - 1, absolute + (event.key === "ArrowUp" ? -1 : 1))), true); }
          }}>{columns.map((column) => <td key={column} className={["profit", "net_pnl"].includes(column) ? Number(row[column]) < 0 ? "negative" : "positive" : undefined}>{formatCell(column, row[column])}</td>)}</tr>;
      })}</tbody></table></div>
    </div>
    <details hidden={view === "trades"}><summary>{t(run.execution_mode === "CANDLESCOPE" ? "native.external.raw" : "native.raw")}</summary><pre>{JSON.stringify(result.raw_output, null, 2)}</pre></details>
  </section>;
}
