import { useEffect, useMemo, useRef, useState } from "react";
import { t } from "../../../i18n/index.js";
import { defaultReplayV2Api } from "../replayV2Api.js";
import { buildEquityPolyline } from "../replayIntegrityModel.js";
import type { PortfolioCurveResponse } from "../portfolioCurve.js";

export default function ReplayPortfolioCurve({ runId }: { readonly runId: string | null }) {
  const [data, setData] = useState<PortfolioCurveResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const active = useRef<AbortController | null>(null);
  useEffect(() => {
    setData(null);
    setError(null);
    setBusy(false);
    return () => { active.current?.abort(); active.current = null; };
  }, [runId]);
  const visible = data?.run_id === runId ? data : null;
  const points = useMemo(() => buildEquityPolyline(visible?.samples ?? [], 420, 112), [visible]);
  const load = async () => {
    if (runId === null) return;
    active.current?.abort();
    const request = new AbortController();
    active.current = request;
    setBusy(true);
    setError(null);
    try {
      const result = await defaultReplayV2Api.portfolioEquityRun(runId, request.signal);
      if (result.run_id !== runId) throw new Error("portfolio run changed");
      if (active.current === request) setData(result);
    } catch (cause) {
      if (!request.signal.aborted && active.current === request) {
        setError(cause instanceof Error ? cause.message : t("replay.rt.integrityLoad"));
      }
    } finally {
      if (active.current === request) setBusy(false);
    }
  };
  return <details className="replay-portfolio-curve">
    <summary>{t("replay.portfolio.title")}</summary>
    <p>{t("replay.portfolio.hint")}</p>
    <button type="button" disabled={busy || runId === null} onClick={() => void load()}>
      {busy ? t("replay.integrity.loading") : t("replay.portfolio.load")}
    </button>
    {error !== null && <p role="alert">{error}</p>}
    {visible !== null && !visible.available && <p>{t("replay.portfolio.empty")}</p>}
    {visible?.available && <>
      <p>{t("replay.portfolio.coverage", { hours: (visible.span_ms / 3600000).toFixed(1), count: visible.samples.length })}</p>
      <svg className="replay-equity-chart" viewBox="0 0 420 112" role="img" aria-label={t("replay.portfolio.title")}>
        <polyline points={points} fill="none" vectorEffect="non-scaling-stroke" />
      </svg>
      <p>{t("replay.portfolio.drawdown")}: {visible.summary?.max_drawdown}</p>
      {runId !== null && <a href={defaultReplayV2Api.portfolioExportUrl(runId)} download>{t("replay.portfolio.export")}</a>}
    </>}
  </details>;
}
