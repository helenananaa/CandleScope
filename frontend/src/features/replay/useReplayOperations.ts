import { useLayoutEffect, useMemo } from "react";
import { useReplayDataManager } from "./replayDataContext.js";
import { ReplayDataManager, type ReplayOperationIdentity } from "./replayDataManager.js";
import { managedReplayRunApi } from "./managedReplayTransport.js";

/** A run owns commands even when its selected chart/session changes. */
export function useReplayOperations(runId: string, purpose: ReplayOperationIdentity["purpose"]) {
  const root = useReplayDataManager();
  const manager = useMemo(() => root?.replay ?? new ReplayDataManager(), [root]);
  const operations = useMemo(() => manager.createOperations({ runId, purpose }), [manager, runId, purpose]);
  // Retain before passive effects start requests, including child effects.
  useLayoutEffect(() => operations.retain(), [operations]);
  const api = useMemo(() => managedReplayRunApi(operations), [operations]);
  return { operations, api };
}
