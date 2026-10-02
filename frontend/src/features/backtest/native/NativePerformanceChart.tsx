import { useEffect, useMemo, useRef, useState } from "react";
import { t } from "../../../i18n/index.js";
import { useLocale } from "../../../i18n/useLocale.js";
import type { NativeResult } from "./nativeBacktestApi.js";
import { reportAnalytics } from "./nativeReportAnalytics.js";

export function NativePerformanceChart({ result }: { result: NativeResult }) {
  const locale = useLocale();
  const data = useMemo(() => reportAnalytics(result), [result]);
  const [metric, setMetric] = useState<"return" | "equity" | "drawdown">("return");
  const [benchmark, setBenchmark] = useState(true);
  const [selected, setSelected] = useState<number | null>(null);
  const host = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(800);
  useEffect(() => {
    if (!host.current) return;
    const observer = new ResizeObserver(entries => setWidth(Math.max(280, entries[0]!.contentRect.width)));
    observer.observe(host.current);
    return () => observer.disconnect();
  }, []);
  const points = data.series.map(point => ({ time: point.time, value: metric === "equity" ? point.value : metric === "drawdown" ? point.drawdownPercent : point.returnPercent }));
  const reference = metric === "return" && benchmark ? data.benchmark : [];
  const values = [...points, ...reference].flatMap(point => point.value == null ? [] : [point.value]);
  const low = values.reduce((a, b) => Math.min(a, b), metric === "equity" ? values[0] ?? 0 : 0), high = values.reduce((a, b) => Math.max(a, b), metric === "equity" ? values[0] ?? 0 : 0);
  const span = high - low || 1;
  const start = points[0]?.time ?? 0, end = points.at(-1)?.time ?? start;
  const right = width - 76, left = 8, top = 18, bottom = 150;
  const x = (time: number) => left + (time - start) / (end - start || 1) * (right - left);
  const y = (value: number) => bottom - (value - low) / span * (bottom - top);
  const path = (items: typeof points) => {
    let gap = true;
    return items.map(point => {
      if (point.value == null) { gap = true; return ""; }
      const command = `${gap ? "M" : "L"}${x(point.time)},${y(point.value)}`; gap = false; return command;
    }).join(" ");
  };
  const format = (value: number | null | undefined) => value == null ? "—" : `${new Intl.NumberFormat(locale, { maximumFractionDigits: 2 }).format(value)}${metric === "equity" ? "" : "%"}`;
  const current = selected == null ? points.at(-1) : points[Math.min(selected, points.length - 1)];
  const comparison = current && reference.length ? [...reference].reverse().find(p => p.time <= current.time) : null;
  return <div className="native-performance" ref={host}>
    <div className="native-performance-heading"><div className="native-performance-tabs">
      {(["return", "equity", "drawdown"] as const).map(item => <button key={item} aria-pressed={metric === item} onClick={() => setMetric(item)}>{t(`report.${item}`)}</button>)}
    </div>{metric === "return" && <label><input type="checkbox" checked={benchmark} onChange={event => setBenchmark(event.target.checked)} />{t("report.benchmark")}</label>}</div>
    <div className="native-performance-readout" aria-live="off"><span>{current ? new Date(current.time * 1000).toLocaleString(locale) : "—"}</span><strong>{format(current?.value)}</strong>{comparison && <span className="native-benchmark-value">{t("report.benchmark")} {format(comparison.value)}</span>}</div>
    {!values.length ? <p>{t("report.unavailable")}</p> : <svg viewBox={`0 0 ${width} 180`} role="img" tabIndex={0} aria-label={t("report.chartHelp")}
      onMouseLeave={() => setSelected(null)} onKeyDown={event => {
        if (["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) {
          event.preventDefault();
          setSelected(event.key === "Home" ? 0 : event.key === "End" ? points.length - 1 : Math.max(0, Math.min(points.length - 1, (selected ?? points.length - 1) + (event.key === "ArrowLeft" ? -1 : 1))));
        }
      }} onMouseMove={event => {
        const matrix = event.currentTarget.getScreenCTM(); if (!matrix) return;
        const cursor = event.currentTarget.createSVGPoint(); cursor.x = event.clientX; cursor.y = event.clientY;
        const target = start + (cursor.matrixTransform(matrix.inverse()).x - left) / (right - left) * (end - start);
        let nearest = 0;
        for (let i = 1; i < points.length; i++) if (Math.abs(points[i]!.time - target) < Math.abs(points[nearest]!.time - target)) nearest = i;
        setSelected(nearest);
      }}>
      {[0, 1, 2, 3, 4].map(tick => { const value = low + span * tick / 4; return <g key={tick}><line x1={left} x2={right} y1={y(value)} y2={y(value)} className="native-chart-grid" /><text x={right + 10} y={y(value) + 4}>{format(value)}</text></g>; })}
      {[0, .5, 1].map(ratio => <text key={ratio} x={x(start + ratio * (end - start))} y={174} textAnchor={ratio === 0 ? "start" : ratio === 1 ? "end" : "middle"}>{new Date((start + ratio * (end - start)) * 1000).toLocaleDateString(locale, { month: "short", day: "numeric" })}</text>)}
      <path d={path(reference)} className="native-benchmark-line" />
      <path d={path(points)} className={metric === "drawdown" ? "native-drawdown-line" : "native-performance-line"} />
      {selected != null && current?.value != null && <g><line x1={x(current.time)} x2={x(current.time)} y1={top} y2={bottom} className="native-chart-cursor" /><circle cx={x(current.time)} cy={y(current.value)} r={3} fill="currentColor" /></g>}
    </svg>}
    <p className="native-report-caption">{t(metric === "return" ? "report.returnBasis" : metric === "equity" ? "report.equityBasis" : "report.drawdownBasis")}{metric === "return" && benchmark && <> · {t("report.benchmarkBasis")}</>}</p>
  </div>;
}
