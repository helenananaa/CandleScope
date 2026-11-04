import type { TrainingHubApiBoundary } from "./useTrainingHub.js";
import type { ReplayOperationLease } from "./replayDataManager.js";
import { defaultReplayV2Api, type ReplayV2ApiClient } from "./replayV2Api.js";
import type { ReplayRuntimeLifecycleOptions } from "./useReplayRuntime.js";

export type ManagedReplayApi = Pick<ReplayV2ApiClient, keyof ReplayV2ApiClient>;

/** Enclose the entire parsed operation, including existing retries, in the lease.
 * Commands remain distinct and keep their original envelope and retry policy. */
export function managedReplayRunApi(lease: ReplayOperationLease, api: ManagedReplayApi = defaultReplayV2Api): ManagedReplayApi {
  return {
    preparationCapabilities: (signal) => lease.request(s => api.preparationCapabilities(s), signal),
    capabilities: (signal) => lease.request(s => api.capabilities(s), signal),
    catalog: (query, signal) => lease.request(s => api.catalog(query, s), signal),
    marketCatalog: (runId, signal) => lease.request(s => api.marketCatalog(runId, s), signal),
    listRuns: (query, signal) => lease.request(s => api.listRuns(query, s), signal),
    createRun: (payload, signal) => lease.request(s => api.createRun(payload, s), signal),
    selectInitialMarket: (runId, payload, signal) => lease.request(s => api.selectInitialMarket(runId, payload, s), signal),
    planInitialMarket: (runId, payload, signal) => lease.request(s => api.planInitialMarket(runId, payload, s), signal),
    deleteRun: (runId, signal) => lease.request(s => api.deleteRun(runId, s), signal),
    segmentPlan: (payload, signal) => lease.request(s => api.segmentPlan(payload, s), signal),
    storageInventory: (signal) => lease.request(s => api.storageInventory(s), signal),
    storageGcPlan: (protocol, request, signal) => lease.request(s => api.storageGcPlan(protocol, request, s), signal),
    storageGcRun: (plan, signal) => lease.request(s => api.storageGcRun(plan, s), signal),
    storageRehydrate: (protocol, objectId, signal) => lease.request(s => api.storageRehydrate(protocol, objectId, s), signal),
    prepareIndex: (runId, signal, clientInstanceId) => lease.request(s => api.prepareIndex(runId, s, clientInstanceId), signal),
    portfolioEquityRun: (runId, signal) => lease.request(s => api.portfolioEquityRun(runId, s), signal),
    portfolioExportUrl: run => api.portfolioExportUrl(run),
    getRun: (runId, signal) => lease.request(s => api.getRun(runId, s), signal),
    returnToHub: (runId, signal) => lease.request(s => api.returnToHub(runId, s), signal),
    viewerBySession: (sessionId, signal) => lease.request(s => api.viewerBySession(sessionId, s), signal),
    tapeProjectionBySession: (sessionId, request, signal) => lease.request(s => api.tapeProjectionBySession(sessionId, request, s), signal),
    displayProjectionBySession: (sessionId, binding, signal) => lease.request(s => api.displayProjectionBySession(sessionId, binding, s), signal),
    tracksBySession: (sessionId, signal) => lease.request(s => api.tracksBySession(sessionId, s), signal),
    tracksRun: (runId, signal) => lease.request(s => api.tracksRun(runId, s), signal),
    planMarketTrack: (run, identity, signal, progress) => lease.request(s => api.planMarketTrack(run, identity, s,
      progress ? job => { if (!s.aborted) progress(job); } : undefined), signal),
    auditAccount: (runId, signal) => lease.request(s => api.auditAccount(runId, s), signal),
    resyncHistoricalBook: (runId, signal) => lease.request(s => api.resyncHistoricalBook(runId, s), signal),
    tradeFlowRun: (runId, query, signal) => lease.request(s => api.tradeFlowRun(runId, query, s), signal),
    accountRecordsRun: (runId, query, signal) => lease.request(s => api.accountRecordsRun(runId, query, s), signal),
    commandRun: (runId, command, signal, options) => lease.request(s => api.commandRun(runId, command, s, options), signal),
    previewOrder: (runId, payload, signal) => lease.request(s => api.previewOrder(runId, payload, s), signal),
    orderCapacity: (runId, payload, signal) => lease.request(s => api.orderCapacity(runId, payload, s), signal),
    trainingResultsRun: (runId, signal) => lease.request(s => api.trainingResultsRun(runId, s), signal),
    advanceProgress: (runId, commandId, signal) => lease.request(s => api.advanceProgress(runId, commandId, s), signal),
    periodSummaryStatusRun: (runId, signal) => lease.request(s => api.periodSummaryStatusRun(runId, s), signal),
    preparePeriodSummariesRun: (runId, signal) => lease.request(s => api.preparePeriodSummariesRun(runId, s), signal),
    integrityRun: (runId, signal) => lease.request(s => api.integrityRun(runId, s), signal),
    publicTimesRun: (runId, timelineMs, signal) => lease.request(s => api.publicTimesRun(runId, timelineMs, s), signal),
    equityRun: (runId, resolution, limit, signal) => lease.request(s => api.equityRun(runId, resolution, limit, s), signal),
    rulesRun: (runId, signal) => lease.request(s => api.rulesRun(runId, s), signal),
    currentDrawingRun: (runId, signal) => lease.request(s => api.currentDrawingRun(runId, s), signal),
    notesRun: (runId, trackId, atTimeMs, signal) => lease.request(s => api.notesRun(runId, trackId, atTimeMs, s), signal),
    saveNoteCaptureRun: (runId, trackId, payload, signal) => lease.request(s => api.saveNoteCaptureRun(runId, trackId, payload, s), signal),
    noteCapturesRun: (runId, trackId, captureId, signal) => lease.request(s => api.noteCapturesRun(runId, trackId, captureId, s), signal),
    noteScreenshotRun: (runId, trackId, noteId, revision, captureId, signal) => lease.request(s => api.noteScreenshotRun(runId, trackId, noteId, revision, captureId, s), signal),
    noteLinkOptionsRun: (runId, trackId, query, signal) => lease.request(s => api.noteLinkOptionsRun(runId, trackId, query, s), signal),
    noteVersionsRun: (runId, trackId, noteId, query, signal) => lease.request(s => api.noteVersionsRun(runId, trackId, noteId, query, s), signal),
    saveNoteRun: (runId, trackId, payload, signal) => lease.request(s => api.saveNoteRun(runId, trackId, payload, s), signal),
    recordDrawingRun: (runId, payload, signal) => lease.request(s => api.recordDrawingRun(runId, payload, s), signal),
    recordMarkerRun: (runId, text, commandId, signal) => lease.request(s => api.recordMarkerRun(runId, text, commandId, s), signal),
    reviewRun: (runId, eventId, signal) => lease.request(s => api.reviewRun(runId, eventId, s), signal),
    controlReviewRun: (runId, reviewId, payload, signal) => lease.request(s => api.controlReviewRun(runId, reviewId, payload, s), signal),
    forkRun: (runId, eventId, signal) => lease.request(s => api.forkRun(runId, eventId, s), signal),
    reportRun: (runId, signal) => lease.request(s => api.reportRun(runId, s), signal),
    prepareReplay: (setup, market, progress, signal, key) => lease.request(s => api.prepareReplay(setup, market,
      job => { if (!s.aborted) progress(job); }, s, key), signal),
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

export function managedTrainingHubApi(lease: Pick<ReplayOperationLease, "request">, api: TrainingHubApiBoundary): TrainingHubApiBoundary {
  return {
    ...(api.prepareReplay ? { prepareReplay: (setup, market, progress, signal, key) => lease.request(s => api.prepareReplay!(setup, market, job => { if (!s.aborted) progress(job); }, s, key), signal) } satisfies Partial<TrainingHubApiBoundary> : {}),
    ...(api.preparationCapabilities ? { preparationCapabilities: (signal) => lease.request(s => api.preparationCapabilities!(s), signal) } satisfies Partial<TrainingHubApiBoundary> : {}),
    listRuns: (query, signal) => lease.request(s => api.listRuns(query, s), signal),
    capabilities: (signal) => lease.request(s => api.capabilities(s), signal),
    catalog: (query, signal) => lease.request(s => api.catalog(query, s), signal),
    createRun: (payload, signal) => lease.request(s => api.createRun(payload, s), signal),
    ...(api.deleteRun ? { deleteRun: (runId, signal) => lease.request(s => api.deleteRun!(runId, s), signal) } satisfies Partial<TrainingHubApiBoundary> : {}),
    ...(api.segmentPlan ? { segmentPlan: (payload, signal) => lease.request(s => api.segmentPlan!(payload, s), signal) } satisfies Partial<TrainingHubApiBoundary> : {}),
    ...(api.storageInventory ? { storageInventory: (signal) => lease.request(s => api.storageInventory!(s), signal) } satisfies Partial<TrainingHubApiBoundary> : {}),
    ...(api.storageGcPlan ? { storageGcPlan: (protocol, request, signal) => lease.request(s => api.storageGcPlan!(protocol, request, s), signal) } satisfies Partial<TrainingHubApiBoundary> : {}),
    ...(api.storageGcRun ? { storageGcRun: (plan, signal) => lease.request(s => api.storageGcRun!(plan, s), signal) } satisfies Partial<TrainingHubApiBoundary> : {}),
    ...(api.storageRehydrate ? { storageRehydrate: (protocol, objectId, signal) => lease.request(s => api.storageRehydrate!(protocol, objectId, s), signal) } satisfies Partial<TrainingHubApiBoundary> : {}),
  };
}
