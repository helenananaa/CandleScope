import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { drawingDocumentSessionRegistry as registry } from "../drawings/core/drawingDocumentStore.js";
import { chartCellDrawingScopeBase } from "../chart-workspace/chartWorkspaceDrawingLink.js";
import type { ChartWorkspaceDocument } from "../chart-workspace/chartWorkspaceTypes.js";
import type { ReplayIntegrityRuntime } from "./useReplayIntegrityRuntime.js";
import type { ReplayV2Json } from "./replayV2Types.js";
import { replayReviewDocumentHash, replayReviewDrawingDocument, replayReviewDrawingRecord } from "./replayReviewDrawing.js";

export function replayWorkspaceDrawingCharts(
  value: Readonly<Record<string, unknown>> | null, runId?: string,
): Record<string, Readonly<Record<string, ReplayV2Json>>> {
  const charts = value?.documentSchemaVersion === 2 && value.charts && typeof value.charts === "object" && !Array.isArray(value.charts)
    ? value.charts as Record<string, Readonly<Record<string, ReplayV2Json>>> : {};
  if (!runId || typeof value?.scopeKey !== "string") return charts;
  const originalRun = value.scopeKey.slice("replay-run:".length);
  return Object.fromEntries(Object.entries(charts).map(([scope, chart]) => [
    scope.replace(`replay:${originalRun}:`, `replay:${runId}:`),
    { ...chart, scopeKey: `replay-run:${runId}` },
  ]));
}

/** One serialized evidence writer for every chart, including charts closed later. */
export function useReplayWorkspaceDrawings(runId: string, workspaceId: string,
  document: ChartWorkspaceDocument, integrity: ReplayIntegrityRuntime) {
  const [error, setError] = useState<string | null>(null);
  const charts = useRef<Record<string, Readonly<Record<string, unknown>>>>({});
  const loaded = useRef(new Set<string>());
  const tail = useRef(Promise.resolve());
  const latest = useRef(integrity);
  latest.current = integrity;
  const scopesKey = JSON.stringify([...new Set(Object.keys(document.cells).map((id) =>
    `${chartCellDrawingScopeBase(`replay:${runId}:${workspaceId}`, document, id)}__main`))].sort());
  const scopes = useMemo(() => JSON.parse(scopesKey) as string[], [scopesKey]);
  const flush = useCallback(() => {
    // Capture now: switching/closing a cell cannot change the pending document.
    for (const scope of scopes) {
      if (!registry.isLoaded(scope)) continue;
      const snapshot = registry.getStore(scope).getSnapshot();
      const previous = charts.current[scope];
      if (previous?.documentRevision !== snapshot.documentRevision || !previous) {
        charts.current[scope] = replayReviewDrawingRecord(snapshot, runId);
      }
    }
    const document = { documentSchemaVersion: 2, scopeKey: `replay-run:${runId}`, charts: { ...charts.current } };
    const count = Object.values(document.charts).reduce((total, chart) => total + (Array.isArray(chart.entities) ? chart.entities.length : 0), 0);
    tail.current = tail.current.catch(() => {}).then(async () => {
      try {
        await latest.current.actions.recordDrawing(document, await replayReviewDocumentHash(document), count);
        setError(null);
      } catch (cause) { setError(String(cause)); }
    });
  }, [runId, scopes]);
  useEffect(() => {
    if (!integrity.drawingLoaded || !integrity.currentDrawing) return;
    const existing = integrity.currentDrawing.document;
    const stored = replayWorkspaceDrawingCharts(existing, runId);
    charts.current = { ...stored, ...charts.current };
    for (const scope of scopes) {
      if (loaded.current.has(scope)) continue;
      const store = registry.getStore(scope);
      const record = charts.current[scope] ?? (existing?.documentSchemaVersion === 1 && scope === scopes[0] ? existing : null);
      if (record && !store.dirty) {
        const result = store.loadDocument(replayReviewDrawingDocument(record, scope));
        if (!result.ok) { setError(result.error); continue; }
        registry.markLoaded(scope, store);
        charts.current[scope] = { ...record, scopeKey: `replay-run:${runId}` };
      }
      loaded.current.add(scope);
    }
    let timer: ReturnType<typeof setTimeout> | null = null;
    const unsubscribe = scopes.map((scope) => registry.getStore(scope).subscribe(() => {
      if (timer !== null) clearTimeout(timer);
      timer = setTimeout(() => { timer = null; flush(); }, 500);
    }));
    return () => {
      unsubscribe.forEach((release) => release());
      if (timer !== null) { clearTimeout(timer); flush(); }
    };
  }, [flush, integrity.currentDrawing, integrity.drawingLoaded, runId, scopes]);
  return { error, retry: flush };
}
