import { NativeStrategyReport } from "./NativeStrategyReport.js";
import { useEffect, useRef, useState } from "react";
import { t } from "../../../i18n/index.js";
import { useLocale } from "../../../i18n/useLocale.js";
import { nativeApi, type NativeRun } from "./nativeBacktestApi.js";
import { normalizeComparison, type NativeComparisonSelection, type PinnedStrategyRun, type NativeStrategyInstance } from "./nativeStrategyCollection.js";
import { comparisonConditions, comparisonMetrics, conditionStatus } from "./nativeStrategyComparisonModel.js";

type Candidate = { id: string; name: string; runId: string | undefined; mode: PinnedStrategyRun["mode"] };
type Pinned = PinnedStrategyRun;
const CONDITION_KEYS = ["symbol", "interval", "start", "end", "snapshot", "engine", "fill", "initial", "fees", "slippage"] as const;
const COLORS = ["#38bdf8", "#f59e0b", "#a78bfa", "#34d399"];

export default function NativeStrategyComparison({ items, context, onOpen, saved, onSave }: {
  items: NativeStrategyInstance[]; context: string[]; onOpen(id: string): void;
  saved?: NativeComparisonSelection | undefined; onSave(value: NativeComparisonSelection): void;
}) {
  const locale = useLocale();
  const candidates: Candidate[] = items.map((item) => {
    const mode = item.executionMode ?? "NATIVE";
    return { id: item.id, name: item.name || t("strategyCollection.default"), mode, runId: item.runs[JSON.stringify([mode, ...context])] };
  });
  const [selection, setSelection] = useState(() => normalizeComparison(saved));
  const selectionRef = useRef(selection);
  const saveSelection = (value: NativeComparisonSelection) => { selectionRef.current = value; setSelection(value); onSave(value); };
  const pinned = selection.pinned;
  const setPinned = (change: (value: Pinned[]) => Pinned[]) => saveSelection({ ...selectionRef.current, pinned: change(selectionRef.current.pinned) });
  const [inspected, setInspected] = useState<{ name: string; run: NativeRun } | null>(null);
  const [reports, setReports] = useState<Record<string, { run?: NativeRun; error?: string }>>({});
  const metric = selection.metric;
  const setMetric = (value: NativeComparisonSelection["metric"]) => saveSelection({ ...selectionRef.current, metric: value });
  useEffect(() => {
    const controller = new AbortController();
    setReports({});
    for (const item of pinned) {
      void nativeApi<NativeRun>(`/${item.mode === "CANDLESCOPE" ? "external" : "native"}/runs/${encodeURIComponent(item.runId)}`, undefined, undefined, controller.signal)
        .then((run) => { if (!controller.signal.aborted) setReports((value) => ({ ...value, [item.id]: { run } })); })
        .catch((reason) => { if (!controller.signal.aborted) setReports((value) => ({ ...value, [item.id]: { error: String(reason) } })); });
    }
    return () => controller.abort();
  }, [pinned]);
  const ready = pinned.flatMap((item, index) => {
    const run = reports[item.id]?.run;
    return run?.state === "COMPLETED" && run.result ? [{ item, index, run, metrics: comparisonMetrics(run), conditions: comparisonConditions(run) }] : [];
  });
  const checks = ready.length > 1 ? CONDITION_KEYS.map((key) => conditionStatus(ready.map((entry) => entry.conditions[key] ?? null))) : ["unknown"];
  const overall = checks.includes("different") ? "different" : checks.includes("unknown") ? "unknown" : "same";
  const format = (value: number | null) => value === null ? "—" : `${new Intl.NumberFormat(locale, { maximumFractionDigits: 2 }).format(value)}%`;
  const points = ready.flatMap((entry) => entry.metrics.points.filter((p) => p[metric] !== null));
  const times = points.map((p) => p.time);
  const values = points.flatMap((p) => p[metric] === null ? [] : [p[metric]!]);
  const xMin = times.reduce((min, value) => Math.min(min, value), Infinity), xMax = times.reduce((max, value) => Math.max(max, value), -Infinity);
  const yMin = values.reduce((min, value) => Math.min(min, value), 0), yMax = values.reduce((max, value) => Math.max(max, value), 0);
  const x = (time: number) => 58 + (time - xMin) / (xMax - xMin || 1) * 864;
  const y = (value: number) => 16 + (yMax - value) / (yMax - yMin || 1) * 150;
  const date = (time: number) => new Date(time * 1000).toLocaleDateString(locale);
  return <section className="native-comparison" aria-label={t("strategyCompare.title")}>
    {inspected ? <>
      <div className="native-comparison-run"><button onClick={() => setInspected(null)}>{t("strategyCompare.back")}</button><strong>{inspected.name}</strong><code>{inspected.run.run_id}</code></div>
      <details><summary>{t("native.source")}</summary><pre>{inspected.run.config?.source}</pre><pre>{JSON.stringify(inspected.run.config?.parameters, null, 2)}</pre></details>
      <NativeStrategyReport run={inspected.run} active={false} />
    </> : <>
    <label className="native-strategy-name">{t("strategyCompare.groupName")}<input maxLength={80} value={selection.name} placeholder={t("strategyCompare.title")}
      onChange={(event) => saveSelection({ ...selectionRef.current, name: event.target.value })} /></label>
    <fieldset className="native-comparison-picker"><legend>{t("strategyCompare.pick")}</legend>
      {candidates.map((item) => <label key={item.id}><input type="checkbox" checked={pinned.some((p) => p.id === item.id)}
        disabled={!item.runId || (pinned.length >= 4 && !pinned.some((p) => p.id === item.id))}
        onChange={(event) => { if (event.target.checked && item.runId) setPinned((value) => [...value, { ...item, runId: item.runId! }]); else setPinned((value) => value.filter((p) => p.id !== item.id)); }} />
        {item.name}{!item.runId && ` · ${t("strategyReview.status.idle")}`}</label>)}
      <button disabled={!pinned.length} onClick={() => setPinned((value) => value.map((item) => {
        const latest = candidates.find((c) => c.id === item.id); return latest?.runId ? { ...latest, runId: latest.runId } : item;
      }))}>{t("strategyCompare.refresh")}</button>
    </fieldset>
    <p className="native-comparison-note">{t("strategyCompare.frozen")}</p>
    {pinned.length < 2 && <p role="status">{t("strategyCompare.empty")}</p>}
    {pinned.map((item) => {
      const state = reports[item.id];
      const latest = candidates.find((c) => c.id === item.id);
      return <div key={item.id} className="native-comparison-run">
        <strong>{item.name}</strong> <code>{item.runId}</code>
        {latest?.runId && latest.runId !== item.runId && <span>{t("strategyCompare.older")}</span>}
        {!state && <span role="status">{t("native.loading")}</span>}
        {state?.error && <span role="alert">{state.error}</span>}
        {state?.run && (state.run.state !== "COMPLETED" || !state.run.result) && <span>{state.run.state} · {t("strategyCompare.unavailable")}</span>}
        <button disabled={!state?.run?.result} onClick={() => { if (state?.run) setInspected({ name: item.name, run: state.run }); }}>{t("strategyCompare.exactRun")}</button>
        <button disabled={!latest} onClick={() => onOpen(item.id)}>{t("strategyCompare.current")}</button>
        <button onClick={() => setPinned((value) => value.filter((p) => p.id !== item.id))}>{t("strategyCollection.remove")}</button>
      </div>;
    })}
    {ready.length > 0 && <>
      <div className="native-comparison-table"><table><thead><tr><th>{t("strategyCompare.metric")}</th>{ready.map(({ item, index }) => <th key={item.id}><span style={{ color: COLORS[index] }}>━</span> {item.name}</th>)}</tr></thead>
        <tbody>{(["returns", "maxDrawdown", "trades", "winRate"] as const).map((key) => <tr key={key}><th>{t(`strategyCompare.${key}`)}</th>{ready.map(({ item, metrics }) => <td key={item.id}>{key === "trades" ? metrics.trades : format(metrics[key])}</td>)}</tr>)}</tbody></table></div>
      <div className="native-comparison-chart-actions">{(["returnPct", "drawdownPct"] as const).map((key) => <button key={key} aria-pressed={key === metric} onClick={() => setMetric(key)}>{t(`strategyCompare.${key}`)}</button>)}</div>
      {points.length > 1 && <svg className="native-comparison-chart" viewBox="0 0 940 205" role="img" aria-label={t(`strategyCompare.${metric}`)}>
        {[0, .5, 1].map((fraction) => <g key={fraction}><line x1="58" x2="922" y1={16 + fraction * 150} y2={16 + fraction * 150} stroke="currentColor" opacity=".15" /><text x="50" y={20 + fraction * 150} textAnchor="end" fill="currentColor">{format(yMax - (yMax - yMin) * fraction)}</text></g>)}
        {ready.map(({ item, metrics, index }) => <path key={item.id} fill="none" stroke={COLORS[index]} strokeWidth="2" strokeDasharray={index % 2 ? "6 3" : undefined}
          d={metrics.points.reduce((state, p) => { if (p[metric] === null) return { d: state.d, start: true }; return { d: `${state.d} ${state.start ? "M" : "L"}${x(p.time)},${y(p[metric]!)}`, start: false }; }, { d: "", start: true }).d}><title>{item.name}</title></path>)}
        <text x="58" y="194" fill="currentColor">{date(xMin)}</text><text x="922" y="194" fill="currentColor" textAnchor="end">{date(xMax)}</text>
      </svg>}
      <p className="native-comparison-note">{t("strategyCompare.basis")}</p>
      <p className="native-comparison-note">{t("strategyCompare.caution")}</p>
      <details><summary>{t("strategyCompare.conditions")} · {t(`strategyCompare.${overall}`)}</summary>
        <div className="native-comparison-table"><table><thead><tr><th>{t("strategyCompare.metric")}</th><th>{t("strategyCompare.check")}</th>{ready.map(({ item }) => <th key={item.id}>{item.name}</th>)}</tr></thead><tbody>
          {CONDITION_KEYS.map((key) => <tr key={key}><th>{t(`strategyCompare.condition.${key}`)}</th><td>{t(`strategyCompare.${conditionStatus(ready.map((entry) => entry.conditions[key] ?? null))}`)}</td>{ready.map(({ item, conditions }) => <td key={item.id}>{conditions[key] ?? "—"}</td>)}</tr>)}
        </tbody></table></div>
      </details>
    </>}
    </>}
  </section>;
}
