import { useEffect, useId, useRef, useState } from "react";
import { t } from "../../i18n/index.js";
import { useLocale } from "../../i18n/useLocale.js";
import { defaultBacktestApi } from "../backtest/backtestApi.js";
import { getChartStrategyDraftStore, createChartStrategyDraftId } from "../backtest/chart-tester/chartStrategyTesterDrafts.js";
import type { ChartWorkspaceRuntime } from "../chart-workspace/useChartWorkspaceRuntime.js";
import { projectSelectedVersion, readResearchReturn, ResearchReturnUnsupported, type ResearchSelectedVersion } from "./researchSelectedVersion.js";
import { researchReturnError } from "./researchReturnError.js";
import "./researchReturn.css";

export default function ResearchReturnDialog({ id, workspace, onClose, onApplied }: {
  id: string; workspace: ChartWorkspaceRuntime; onClose(): void; onApplied(cellId: string): void;
}) {
  const locale = useLocale(), title = useId(), dialog = useRef<HTMLDialogElement>(null);
  const [reference] = useState(() => readResearchReturn(id));
  const [version, setVersion] = useState<ResearchSelectedVersion | null>(null);
  const [error, setError] = useState<string | null>(null), [busy, setBusy] = useState(false);
  const [cell, setCell] = useState("");
  const [requestId, setRequestId] = useState<string | null>(null);
  const alive = useRef(true), submitting = useRef(false);
  const pendingCell = useRef<string | null>(null);
  useEffect(() => {
    alive.current = true;
    const previous = document.activeElement;
    const element = dialog.current;
    element?.showModal();
    return () => { alive.current = false; element?.close(); if (previous instanceof HTMLElement && previous.isConnected) previous.focus(); };
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    void (async () => {
      try {
        if (!reference) throw new ResearchReturnUnsupported("reference");
        const selected = await defaultBacktestApi.getSelectedVersion!(reference.runId, controller.signal);
        if (selected.version_hash !== reference.versionHash) throw new ResearchReturnUnsupported("version");
        projectSelectedVersion(selected);
        if (!controller.signal.aborted) setVersion(selected);
      } catch (failure) { if (!controller.signal.aborted) setError(researchReturnError(failure)); }
    })();
    return () => controller.abort();
  }, [reference]);
  const originCell = reference?.origin?.workspaceId === workspace.view.activeWorkspaceId ? reference.origin.cellId : "";
  const cellId = workspace.view.layoutCellIds.includes(cell) ? cell
    : workspace.view.layoutCellIds.includes(originCell) ? originCell : workspace.view.activeCellId;
  const receipt = workspace.status.controlReceipt;
  useEffect(() => {
    if (!requestId || receipt?.requestId !== requestId) return;
    if (receipt.ok && pendingCell.current) onApplied(pendingCell.current);
    else { setBusy(false); submitting.current = false; setError(t("researchReturn.changed")); setRequestId(null); }
  }, [requestId, receipt, onApplied]);
  async function apply() {
    if (submitting.current || !version || !workspace.view.ready) return;
    const target = workspace.view.document.cells[cellId];
    if (!target) return;
    submitting.current = true; setBusy(true); setError(null);
    // Capture the target before persistence. The atomic workspace command
    // rejects edits, workspace switches, closed targets and window changes.
    const expectation = { workspaceId: workspace.view.activeWorkspaceId, windowId: workspace.view.window.id,
      expectedRevision: workspace.view.document.revision };
    const projection = projectSelectedVersion(version);
    try {
      const draft = await getChartStrategyDraftStore().save({ id: createChartStrategyDraftId(), displayName: version.program.name,
        language: version.program.language, source: version.program.source_text, cursor: null });
      if (!alive.current) return;
      const nextId = crypto.randomUUID(); pendingCell.current = cellId; setRequestId(nextId);
      workspace.actions.applyControlCommand({ ...expectation, requestId: nextId, charts: [{ cellId,
        session: projection.session, indicators: target.indicators,
        strategyAttachment: { ...projection.attachment, strategyDraftId: draft.id } }] });
    } catch (failure) {
      if (alive.current) { submitting.current = false; setBusy(false); setError(researchReturnError(failure)); }
    }
  }
  const projected = version ? projectSelectedVersion(version) : null;
  return <dialog ref={dialog} className="research-return-dialog" aria-labelledby={title} onCancel={(event) => { event.preventDefault(); if (!busy) onClose(); }}>
    <h2 id={title}>{t("researchReturn.title")}</h2>
    <p>{t("researchReturn.help")}</p>
    {version && projected ? <>
      <p>{version.program.name} · {projected.session.exchange} · {projected.session.symbol} · {projected.session.interval}</p>
      <p>{t("researchReturn.version", { run: version.run_id, revision: version.strategy_revision_id })}</p>
      <p>{new Date(projected.attachment.customRange!.startMs).toLocaleString(locale)} — {new Date(projected.attachment.customRange!.endMs).toLocaleString(locale)}</p>
      <label>{t("researchReturn.workspace")}<select aria-label={t("researchReturn.workspace")} disabled={busy} value={workspace.view.activeWorkspaceId} onChange={(event) => { setCell(""); workspace.actions.switchWorkspace(event.target.value); }}>
        {workspace.view.workspaces.map((value) => <option key={value.id} value={value.id}>{value.name}</option>)}
      </select></label>
      <label>{t("researchReturn.target")}<select aria-label={t("researchReturn.target")} disabled={busy} value={cellId} onChange={(event) => setCell(event.target.value)}>
        {workspace.view.layoutCellIds.map((key) => <option key={key} value={key}>{key} · {workspace.view.document.cells[key]?.session.symbol}{key === originCell ? ` · ${t("researchReturn.origin")}` : ""}</option>)}
      </select></label>
    </> : !error && <p role="status">{t("researchReturn.loading")}</p>}
    {error && <p role="alert">{error}</p>}
    <footer><button type="button" className="ui-control" disabled={busy} onClick={onClose}>{t("chartTime.close")}</button>
      <button type="button" className="ui-control" disabled={busy || !version || !workspace.view.ready} onClick={() => { void apply(); }}>{t("researchReturn.apply")}</button></footer>
  </dialog>;
}
