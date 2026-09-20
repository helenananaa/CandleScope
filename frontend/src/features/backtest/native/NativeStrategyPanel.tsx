import { useEffect, useRef, useState } from "react";
import type { ChartStrategyTesterPanelProps } from "../chart-tester/ChartStrategyTesterPanel.js";
import type { ChartContextResolution } from "../backtestApi.js";
import { t } from "../../../i18n/index.js";
import { useLocale } from "../../../i18n/useLocale.js";
import { nativeApi, nativeTerminal, nativeTimeframe, type NativeCapabilities, type NativeRun } from "./nativeBacktestApi.js";
import { NativeStrategyReport } from "./NativeStrategyReport.js";
import "./nativeStrategy.css";
import { NativeAdvancedInputs } from "./NativeAdvancedInputs.js";
import { emptyAdvancedInputs, executionInputs, freezeAdvancedInputs, type AdvancedInputs } from "./nativeInputs.js";

const NATIVE_TEMPLATES = {
  pine: '//@version=6\nstrategy("Native SMA", overlay=true, initial_capital=10000)\nfast = ta.sma(close, 3)\nslow = ta.sma(close, 5)\nif ta.crossover(fast, slow)\n    strategy.entry("L", strategy.long)\nif ta.crossunder(fast, slow)\n    strategy.close("L")\nplot(fast)\nplot(slow)\n',
  pyne: 'strategy("Native SMA", overlay=True, initial_capital=10000)\nfast = ta.sma(close, 3)\nslow = ta.sma(close, 5)\nstrategy.entry_when(ta.crossover(fast, slow), "L", strategy.long, qty=1)\nstrategy.close_when(ta.crossunder(fast, slow), "L")\nplot(fast, "Fast")\nplot(slow, "Slow")\n',
};

export default function NativeStrategyPanel(props: Pick<ChartStrategyTesterPanelProps, "session" | "cellScope" | "onClose" | "onLocateTrade"> & {
  dataset?: { datasetId: string; dataEpoch: string } | undefined;
  onRunChange?: (run: NativeRun | null) => void;
  externalReport?: boolean;
}) {
  const locale = useLocale();
  const [language, setLanguage] = useState<"pine" | "pyne">("pine");
  const [mode, setMode] = useState<"NATIVE" | "CANDLESCOPE">("NATIVE");
  const [hostSettings, setHostSettings] = useState({ initial_balance: 10000, slippage_bps: 1, taker_fee_bps: 0, price_tick: 0.01 });
  const [fidelity, setFidelity] = useState("BAR_APPROX");
  const [fillRecalculation, setFillRecalculation] = useState(false);
  const [executionData, setExecutionData] = useState<unknown>(null);
  const [executionDataState, setExecutionDataState] = useState<"ready" | "loading" | "invalid">("ready");
  const executionUpload = useRef(0);
  const runPath = mode === "NATIVE" ? "/native/runs" : "/external/runs";
  const [source, setSource] = useState(NATIVE_TEMPLATES.pine);
  const [advanced, setAdvanced] = useState<AdvancedInputs>(emptyAdvancedInputs);
  const [parameters, setParameters] = useState("{}");
  const [capabilities, setCapabilities] = useState<NativeCapabilities | null>(null);
  const [run, setRun] = useState<NativeRun | null>(null);
  const [history, setHistory] = useState<NativeRun[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [resolution, setResolution] = useState<ChartContextResolution | null>(null);
  const alive = useRef(true);
  const storageKey = `candlescope.native-draft:${props.cellScope}:${language}`;
  const onRunChange = props.onRunChange;
  useEffect(() => { onRunChange?.(run); }, [run, onRunChange]);
  useEffect(() => {
    alive.current = true;
    void nativeApi<NativeCapabilities>("/native/capabilities").then(setCapabilities).catch((reason) => setError(String(reason)));
    return () => { alive.current = false; };
  }, []);
  useEffect(() => {
    const abort = new AbortController();
    void nativeApi<{ runs: NativeRun[] }>(runPath, undefined, undefined, abort.signal).then((value) => setHistory(value.runs))
      .catch((reason) => { if (!abort.signal.aborted) setError(String(reason)); });
    return () => abort.abort();
  }, [runPath]);
  useEffect(() => {
    try { const saved = localStorage.getItem(storageKey); const draft: unknown = saved ? JSON.parse(saved) : null;
      setSource(draft && typeof draft === "object" && "source" in draft && typeof draft.source === "string" ? draft.source : NATIVE_TEMPLATES[language]);
      setParameters(draft && typeof draft === "object" && "parameters" in draft && typeof draft.parameters === "string" ? draft.parameters : "{}");
    } catch { setSource(NATIVE_TEMPLATES[language]); setParameters("{}"); }
    setAdvanced(emptyAdvancedInputs());
  }, [storageKey, language]);
  useEffect(() => { setResolution(null); }, [props.session.exchange, props.session.marketType, props.session.symbol, props.session.interval]);
  const save = (text: string, params: string) => {
    setSource(text); setParameters(params);
    try { localStorage.setItem(storageKey, JSON.stringify({ source: text, parameters: params })); } catch { setError(t("native.saveFailed")); }
  };
  useEffect(() => {
    if (!run || nativeTerminal(run.state)) return;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      void nativeApi<NativeRun>(`${run.execution_mode === "CANDLESCOPE" ? "/external/runs" : "/native/runs"}/${run.run_id}`, undefined, undefined, controller.signal)
        .then((value) => { setRun(value); if (nativeTerminal(value.state)) { setBusy(false); setHistory((items) => [value, ...items.filter((item) => item.run_id !== value.run_id)]); } })
        .catch((reason) => { if (!controller.signal.aborted) { setError(String(reason)); setBusy(false); } });
    }, 700);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [run]);
  const start = async (prepare = false) => {
    setBusy(true); setError(""); setRun(null);
    try {
      const params: unknown = JSON.parse(parameters);
      if (!params || Array.isArray(params) || typeof params !== "object") throw new Error(t("native.parametersInvalid"));
      const context = props.session;
      const execution = executionInputs(mode, hostSettings, fidelity, fillRecalculation, executionData);
      if (props.dataset) {
        const catalog = await nativeApi<{ datasets: Array<{ dataset_id: string; data_epoch: string; first_open_ms: number; last_close_ms: number }> }>("/datasets");
        const dataset = catalog.datasets.find((item) => item.dataset_id === props.dataset!.datasetId && item.data_epoch === props.dataset!.dataEpoch);
        if (!dataset) throw new Error("DATA_SNAPSHOT_MISMATCH: imported dataset changed");
        const data = { dataset_id: dataset.dataset_id, data_epoch: dataset.data_epoch, start_time_ms: dataset.first_open_ms,
          end_time_ms: dataset.last_close_ms, interval: context.interval, exchange: context.exchange, market_type: context.marketType };
        const snapshot = await nativeApi<{ snapshot_hash: string }>("/datasets/snapshot", data);
        const inputs = await freezeAdvancedInputs(advanced, language, data);
        const result = await nativeApi<NativeRun>(runPath, { ...data, ...inputs, ...execution, snapshot_hash: snapshot.snapshot_hash,
          language, source, parameters: params, context: { symbol: context.symbol, timeframe: nativeTimeframe(context.interval) } }, crypto.randomUUID());
        if (alive.current) setRun(result);
        return;
      }
      const frozen = prepare && resolution ? await nativeApi<ChartContextResolution>("/chart-context/materialize", {
        resolution_token: resolution.resolution_token, user_confirmed: true, idempotency_key: crypto.randomUUID(),
      }) : await nativeApi<ChartContextResolution>("/chart-context/resolve", {
        exchange: context.exchange, market_type: context.marketType, symbol: context.symbol,
        interval: context.interval, range_mode: "ALL_AVAILABLE", fidelity_preference: "FAST",
      });
      if (!alive.current) return;
      setResolution(frozen);
      if (frozen.status !== "READY") { setBusy(false); return; }
      const inputs = await freezeAdvancedInputs(advanced, language, {
        start_time_ms: frozen.coverage.requested_start_ms ?? frozen.coverage.available_start_ms!,
        end_time_ms: frozen.coverage.requested_end_ms ?? frozen.coverage.available_end_ms!,
        exchange: context.exchange, market_type: context.marketType,
      });
      const result = await nativeApi<NativeRun>(runPath, { ...inputs, ...execution,
        language, source, parameters: params, dataset_id: frozen.dataset_id, data_epoch: frozen.data_epoch,
        snapshot_hash: frozen.snapshot_hash, start_time_ms: frozen.coverage.requested_start_ms ?? frozen.coverage.available_start_ms,
        end_time_ms: frozen.coverage.requested_end_ms ?? frozen.coverage.available_end_ms,
        interval: context.interval, exchange: context.exchange, market_type: context.marketType,
        context: { symbol: `${context.exchange.toUpperCase()}:${context.symbol}`, timeframe: nativeTimeframe(context.interval) },
      }, crypto.randomUUID());
      if (alive.current) setRun(result);
    } catch (reason) { if (alive.current) { setError(String(reason)); setBusy(false); } }
  };
  const available = capabilities?.engines.find((item) => item.language === language);
  return <section className="native-strategy-panel" aria-label={t("native.title")}>
    <header><strong>{t(mode === "NATIVE" ? "native.title" : "native.external.title")}</strong><span>{props.session.symbol} · {props.session.interval}</span><button onClick={props.onClose}>×</button></header>
    <div className="native-toolbar"><button aria-pressed={mode === "NATIVE"} disabled={busy} onClick={() => { setMode("NATIVE"); setAdvanced(emptyAdvancedInputs()); setRun(null); }}>{t("native.title")}</button>
      <button aria-pressed={mode === "CANDLESCOPE"} disabled={busy} onClick={() => { setMode("CANDLESCOPE"); setAdvanced(emptyAdvancedInputs()); setRun(null); }}>{t("native.external.title")}</button></div>
    <p>{t(mode === "NATIVE" ? "native.description" : "native.external.description")}</p>
    {mode === "CANDLESCOPE" && <div className="native-toolbar">{(["initial_balance", "slippage_bps", "taker_fee_bps", "price_tick"] as const).map((field) => <label key={field}>{t(`native.external.${field}`)}
      <input type="number" min="0" step="any" disabled={busy} value={hostSettings[field]} onChange={(event) => setHostSettings((value) => ({ ...value, [field]: Number(event.target.value) }))} />
    </label>)}</div>}
    {mode === "CANDLESCOPE" && <div className="native-toolbar">
      <label>{t("native.external.fidelity")}<select disabled={busy} value={fidelity} onChange={(event) => { setFidelity(event.target.value); setRun(null); }}>
        <option value="BAR_APPROX">BAR_APPROX</option><option value="TRADE_TAPE">TRADE_TAPE</option><option value="BOOK_ASSISTED">BOOK_ASSISTED</option><option value="BOOK_DEPTH">BOOK_DEPTH</option>
        <option value="BOOK_SAMPLED">{t("native.external.sampledLabel")}</option>
      </select></label>
      {fidelity === "BOOK_DEPTH" && <p>{t("native.external.depthHint")}</p>}
      {fidelity === "BOOK_SAMPLED" && <p>{t("native.external.sampledHint")}</p>}
      {fidelity !== "BAR_APPROX" && <label>{t("native.external.executionData")}<input type="file" accept="application/json,.json" disabled={busy} onChange={(event) => {
        const file = event.target.files?.[0];
        const upload = ++executionUpload.current;
        setExecutionData(null);
        setExecutionDataState(file ? "loading" : "ready");
        if (file) void file.text().then((text) => {
          if (upload !== executionUpload.current) return;
          setExecutionData(JSON.parse(text)); setExecutionDataState("ready"); setError("");
        }).catch((reason) => {
          if (upload !== executionUpload.current) return;
          setExecutionDataState("invalid"); setError(String(reason));
        });
      }} /></label>}
      {fidelity !== "BAR_APPROX" && <><label><input type="checkbox" disabled={busy} checked={fillRecalculation} onChange={(event) => setFillRecalculation(event.target.checked)} />{t("native.external.fillRecalculation")}</label><p>{t("native.external.fillHint")}</p>{fidelity !== "BOOK_SAMPLED" && <p>{t("native.external.dataHint")}</p>}</>}
    </div>}
    <div className="native-toolbar"><select aria-label={t("native.language")} value={language} disabled={busy} onChange={(event) => setLanguage(event.target.value as "pine" | "pyne")}>
      <option value="pine">{t("chartTester.language.pine")}</option><option value="pyne">{t("chartTester.language.pyne")}</option></select>
      <button disabled={busy || (mode === "CANDLESCOPE" && fidelity !== "BAR_APPROX" && executionDataState !== "ready") || !(mode === "NATIVE" ? available?.available : available?.external_available)} onClick={() => void start()}>{t(mode === "NATIVE" ? "native.run" : "native.external.run")}</button>
      {run && !nativeTerminal(run.state) && <button onClick={() => void nativeApi<NativeRun>(`${runPath}/${run.run_id}/cancel`, {}).then((value) => { setRun(value); setBusy(false); }).catch((reason) => setError(String(reason)))}>{t("native.cancel")}</button>}
      <span>{busy ? t("native.running") : run?.state}</span></div>
    {available && !(mode === "NATIVE" ? available.available : available.external_available) && <p role="alert">{t("native.unavailable")} {available.reason}</p>}
    <div className="native-editor"><textarea aria-label={t("native.source")} value={source} disabled={busy} spellCheck={false} onChange={(event) => save(event.target.value, parameters)} />
      <label>{t("native.parameters")}<textarea value={parameters} disabled={busy} onChange={(event) => save(source, event.target.value)} /></label></div>
    {<NativeAdvancedInputs native={mode === "NATIVE"} value={advanced} onChange={setAdvanced} language={language} disabled={busy} exchange={props.session.exchange} />}
    {resolution && resolution.status !== "READY" && <p>{resolution.status} <button disabled={busy} onClick={() => void start(true)}>{t("native.prepare")}</button></p>}
    {(error || run?.error) && <pre role="alert">{error || `${run?.error?.message}\n${JSON.stringify(run?.error?.details ?? {}, null, 2)}`}</pre>}
    {run?.result && !props.externalReport && <><details><summary>{t("native.source")}</summary><pre>{run.config?.source}</pre></details>
      <NativeStrategyReport key={run.run_id} run={run} onLocate={props.onLocateTrade} /></>}
    <details><summary>{t(mode === "NATIVE" ? "native.history" : "native.external.history")}</summary>{history.map((item) => <button key={item.run_id} disabled={busy} onClick={() => void nativeApi<NativeRun>(`${runPath}/${item.run_id}`).then(setRun).catch((reason) => setError(String(reason)))}>
      {new Date(item.created_at_ms).toLocaleString(locale)} · {item.runtime_identity.engine.package} · {item.state}</button>)}</details>
  </section>;
}
