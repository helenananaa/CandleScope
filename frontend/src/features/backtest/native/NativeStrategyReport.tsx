import { useState } from "react";
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

export function NativeStrategyReport({ run, onLocate }: { run: NativeRun; onLocate?: ((time: number) => void) | undefined }) {
  const [replay, setReplay] = useState<NativeReplayRecord | null>(null);
  return <>
    {run.execution_mode !== "CANDLESCOPE" && <NativeReplayControls runId={run.run_id} replay={replay} onChange={setReplay} />}
    <NativeResultBody key={replay?.replay_id ?? run.run_id} run={replay ? { ...run, result: replay.result } : run} onLocate={onLocate}
      exportUrl={replay ? nativeExportUrl(run.run_id).replace(`/runs/${run.run_id}/`, `/replays/${replay.replay_id}/`) : nativeExportUrl(run.run_id, run.execution_mode)} />
  </>;
}

function NativeResultBody({ run, onLocate, exportUrl }: { run: NativeRun; onLocate?: ((time: number) => void) | undefined; exportUrl: string }) {
  const [section, setSection] = useState<"trades" | "orders">("trades");
  const [page, setPage] = useState(0);
  const result = run.result;
  if (!result) return null;
  const rows = result[section];
  const columns = [...new Set(rows.flatMap((row) => Object.keys(row)))];
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
  return <section className="native-report">
    <p><strong>{result.account_authority}</strong> · {run.execution_mode === "CANDLESCOPE" && run.runtime_identity.engine.package} {run.runtime_identity.engine.version} · {result.fill_model}{result.fidelity && <> · {result.fidelity}</>}</p>
    {run.config?.context && <p>{run.config.context.symbol} · {run.config.interval} · {JSON.stringify(run.config.parameters)}</p>}
    <p>{t(run.execution_mode === "CANDLESCOPE" ? "native.external.authority" : "native.authority")}</p>
    {result.fidelity === "BOOK_DEPTH" && <p>{t("native.external.depthHint")}</p>}
    {result.fidelity === "BOOK_SAMPLED" && <p>{t("native.external.sampledHint")}</p>}
    {run.execution_mode === "CANDLESCOPE" && result.raw_output.entry_allocation != null && <p>{t("native.external.allocationHint")}</p>}
    <a href={exportUrl} download>{t(run.execution_mode === "CANDLESCOPE" ? "native.external.export" : "native.export")}</a>
    {result.diagnostics.length > 0 && <pre role="status">{JSON.stringify(result.diagnostics, null, 2)}</pre>}
    <NativeCurve points={result.equity} title={t(run.execution_mode === "CANDLESCOPE" ? "native.external.equity" : "native.equity")} />
    <NativeCurve points={result.bars.map((bar) => ({ time: bar.time, value: bar.close }))} title={t("native.price")} markers={markers} onLocate={onLocate} />
    {graphics.map((graphic, index) => <NativeCurve key={index} {...graphic} />)}
    <NativeDrawingScene result={result} />
    <NativeSeriesScene result={result} />
    <div><button onClick={() => { setSection("trades"); setPage(0); }}>{t("native.trades")} ({result.trades.length})</button>
      <button onClick={() => { setSection("orders"); setPage(0); }}>{t("native.orders")} ({result.orders.length})</button></div>
    <div className="native-table"><table><thead><tr>{columns.map((column) => <th key={column}>{column}</th>)}</tr></thead>
      <tbody>{rows.slice(page * 50, page * 50 + 50).map((row, index) => <tr key={index} onClick={() => {
        const time = Number(row.entryTime ?? row.entry_time ?? row.time);
        if (Number.isFinite(time)) onLocate?.(time * 1000);
      }}>{columns.map((column) => <td key={column}>{typeof row[column] === "object" ? JSON.stringify(row[column]) : String(row[column] ?? "—")}</td>)}</tr>)}</tbody></table></div>
    <button disabled={page === 0} onClick={() => setPage(page - 1)}>←</button> {page + 1} / {Math.max(1, Math.ceil(rows.length / 50))} <button disabled={(page + 1) * 50 >= rows.length} onClick={() => setPage(page + 1)}>→</button>
    <details><summary>{t(run.execution_mode === "CANDLESCOPE" ? "native.external.raw" : "native.raw")}</summary><pre>{JSON.stringify(result.raw_output, null, 2)}</pre></details>
  </section>;
}
