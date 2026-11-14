import { useEffect, useRef, useState } from "react";
import { Button, Dialog, Field, InlineAlert, Section, Select } from "../../components/ui/index.js";
import { t } from "../../i18n/index.js";
import { useLocale } from "../../i18n/useLocale.js";
import { defaultBacktestApi } from "../backtest/backtestApi.js";
import { getChartStrategyDraftStore, createChartStrategyDraftId } from "../backtest/chart-tester/chartStrategyTesterDrafts.js";
import type { ChartWorkspaceRuntime } from "../chart-workspace/useChartWorkspaceRuntime.js";
import { projectSelectedVersion, readResearchReturn, ResearchReturnUnsupported, type ResearchSelectedVersion } from "./researchSelectedVersion.js";
import { researchReturnError } from "./researchReturnError.js";

export default function ResearchReturnDialog({ id, workspace, onClose, onApplied }: {
  id: string; workspace: ChartWorkspaceRuntime; onClose(): void; onApplied(cellId: string): void;
}) {
  const locale = useLocale();
  const [reference] = useState(() => readResearchReturn(id));
  const [version, setVersion] = useState<ResearchSelectedVersion | null>(null);
  const [error, setError] = useState<string | null>(null), [busy, setBusy] = useState(false);
  const [cell, setCell] = useState("");
  const [requestId, setRequestId] = useState<string | null>(null);
  const alive = useRef(true), submitting = useRef(false);
  const pendingCell = useRef<string | null>(null);
  useEffect(() => {
    alive.current = true;
    return () => { alive.current = false; };
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
  return <Dialog open onClose={onClose} dismissible={!busy}
    title={t("researchReturn.title")} description={t("researchReturn.help")}
    footer={<>
      <Button disabled={busy} onClick={onClose}>{t("chartTime.close")}</Button>
      <Button variant="primary" disabled={busy || !version || !workspace.view.ready} onClick={() => { void apply(); }}>{t("researchReturn.apply")}</Button>
    </>}>
    {version && projected ? <Section
      title={`${version.program.name} · ${projected.session.exchange} · ${projected.session.symbol} · ${projected.session.interval}`}
      description={<>
        {t("researchReturn.version", { run: version.run_id, revision: version.strategy_revision_id })}<br />
        {new Date(projected.attachment.customRange!.startMs).toLocaleString(locale)} — {new Date(projected.attachment.customRange!.endMs).toLocaleString(locale)}
      </>}>
      <Field label={t("researchReturn.workspace")}>
        <Select disabled={busy} value={workspace.view.activeWorkspaceId} onChange={(event) => { setCell(""); workspace.actions.switchWorkspace(event.target.value); }}>
          {workspace.view.workspaces.map((value) => <option key={value.id} value={value.id}>{value.name}</option>)}
        </Select>
      </Field>
      <Field label={t("researchReturn.target")}>
        <Select disabled={busy} value={cellId} onChange={(event) => setCell(event.target.value)}>
          {workspace.view.layoutCellIds.map((key) => <option key={key} value={key}>{key} · {workspace.view.document.cells[key]?.session.symbol}{key === originCell ? ` · ${t("researchReturn.origin")}` : ""}</option>)}
        </Select>
      </Field>
      {error && <InlineAlert tone="danger">{error}</InlineAlert>}
    </Section> : error ? <InlineAlert tone="danger">{error}</InlineAlert>
      : <p className="ui-dialog-message" role="status">{t("researchReturn.loading")}</p>}
  </Dialog>;
}
