import { useLayoutEffect, useMemo } from "react";
import { useReplayDataManager, useReplayRunId } from "./replayDataContext.js";
import { ReplayDataManager, type ReplayOperationIdentity } from "./replayDataManager.js";
import { managedReplayAdapterApi, managedReplayRunApi } from "./managedReplayTransport.js";
import { defaultReplayApi } from "./replayApi.js";
import { useMarketDataWorkspaceResources } from "../market-data/marketDataWorkspaceContext.js";

/** A run owns commands even when its selected chart/session changes. */
export function useReplayOperations(runId: string | null | undefined, purpose: ReplayOperationIdentity["purpose"], scope?: string) {
  const root = useReplayDataManager();
  const live = useMarketDataWorkspaceResources();
  const parentRunId = useReplayRunId();
  const identity = runId ?? parentRunId ?? "hub";
  const manager = useMemo(() => root?.replay ?? live?.dataManager.replay ?? new ReplayDataManager(), [root, live?.dataManager]);
  const operations = useMemo(() => manager.createOperations({ runId: identity, purpose,
    ...(scope === undefined ? {} : { scope }) }), [manager, identity, purpose, scope]);
  // Retain before passive effects start requests, including child effects.
  useLayoutEffect(() => operations.retain(), [operations]);
  const api = useMemo(() => managedReplayRunApi(operations), [operations]);
  const adapterApi = useMemo(() => managedReplayAdapterApi(operations, defaultReplayApi), [operations]);
  const request = useMemo(() => operations.request.bind(operations), [operations]);
  return { operations, api, adapterApi, request };
}
