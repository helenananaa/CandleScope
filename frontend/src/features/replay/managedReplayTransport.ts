import type { ReplayOperationLease } from "./replayDataManager.js";
import { defaultReplayV2Api, type ReplayV2ApiClient } from "./replayV2Api.js";
import type { ReplayRuntimeLifecycleOptions } from "./useReplayRuntime.js";

type RunApi = Pick<ReplayV2ApiClient, "getRun" | "prepareIndex" | "viewerBySession" | "tracksBySession"
  | "tracksRun" | "displayProjectionBySession" | "commandRun" | "advanceProgress" | "planMarketTrack"
  | "previewOrder" | "orderCapacity" | "resyncHistoricalBook" | "auditAccount"
  | "periodSummaryStatusRun" | "preparePeriodSummariesRun">;

/** Enclose the entire parsed operation, including existing retries, in the lease.
 * Commands remain distinct and keep their original envelope and retry policy. */
export function managedReplayRunApi(lease: ReplayOperationLease, api: RunApi = defaultReplayV2Api): RunApi {
  return {
    getRun: (run, signal) => lease.request(s => api.getRun(run, s), signal),
    prepareIndex: (run, signal, client) => lease.request(s => api.prepareIndex(run, s, client), signal),
    viewerBySession: (session, signal) => lease.request(s => api.viewerBySession(session, s), signal),
    tracksBySession: (session, signal) => lease.request(s => api.tracksBySession(session, s), signal),
    tracksRun: (run, signal) => lease.request(s => api.tracksRun(run, s), signal),
    displayProjectionBySession: (session, binding, signal) => lease.request(s => api.displayProjectionBySession(session, binding, s), signal),
    commandRun: (run, command, signal, options) => lease.request(s => api.commandRun(run, command, s, options), signal),
    advanceProgress: (run, command, signal) => lease.request(s => api.advanceProgress(run, command, s), signal),
    planMarketTrack: (run, identity, signal, progress) => lease.request(s => api.planMarketTrack(run, identity, s,
      progress ? job => { if (!s.aborted) progress(job); } : undefined), signal),
    previewOrder: (run, request, signal) => lease.request(s => api.previewOrder(run, request, s), signal),
    orderCapacity: (run, request, signal) => lease.request(s => api.orderCapacity(run, request, s), signal),
    resyncHistoricalBook: (run, signal) => lease.request(s => api.resyncHistoricalBook(run, s), signal),
    auditAccount: (run, signal) => lease.request(s => api.auditAccount(run, s), signal),
    periodSummaryStatusRun: (run, signal) => lease.request(s => api.periodSummaryStatusRun(run, s), signal),
    preparePeriodSummariesRun: (run, signal) => lease.request(s => api.preparePeriodSummariesRun(run, s), signal),
  };
}

type AdapterApi = NonNullable<ReplayRuntimeLifecycleOptions["api"]>;
export function managedReplayAdapterApi(lease: ReplayOperationLease, api: AdapterApi): AdapterApi {
  return {
    capabilities: signal => lease.request(s => api.capabilities(s), signal),
    getSession: (session, signal) => lease.request(s => api.getSession(session, s), signal),
    ...(api.command ? { command: (session, command, signal) => lease.request(s => api.command!(session, command, s), signal) } satisfies Partial<AdapterApi> : {}),
    ...(api.report ? { report: (session, signal) => lease.request(s => api.report!(session, s), signal) } satisfies Partial<AdapterApi> : {}),
    ...(api.journal ? { journal: (session, signal) => lease.request(s => api.journal!(session, s), signal) } satisfies Partial<AdapterApi> : {}),
  };
}

type StreamFactory = NonNullable<ReplayRuntimeLifecycleOptions["streamFactory"]>;
export function managedReplayAdapterStreams(lease: ReplayOperationLease, factory: StreamFactory): StreamFactory {
  return options => {
    let owned: { value: ReturnType<StreamFactory>; release(): void; current(): boolean } | null = null;
    return {
      start() {
        if (owned?.current()) return;
        owned = lease.openResource(current => factory({
          ...options,
          shouldHeartbeat: () => current() && (options.shouldHeartbeat?.() === true),
          onGeneration: (...args) => { if (current()) options.onGeneration?.(...args); },
          onState: (...args) => { if (current()) options.onState?.(...args); },
          onSnapshot: (...args) => { if (current()) options.onSnapshot?.(...args); },
          onEvent: (...args) => { if (current()) options.onEvent?.(...args); },
          onError: (...args) => { if (current()) options.onError?.(...args); },
        }), stream => stream.stop());
        try { owned.value.start(); } catch (error) { owned.release(); owned = null; throw error; }
      },
      stop() { owned?.release(); owned = null; },
      requestResync(reason) { if (owned?.current()) owned.value.requestResync(reason); },
    };
  };
}
