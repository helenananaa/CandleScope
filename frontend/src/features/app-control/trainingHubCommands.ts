import type { TrainingHubRuntime } from "../replay/useTrainingHub.js";
import { REPLAY_V2_ENUMS as e } from "../replay/replayV2Types.js";
import { REPLAY_POLICY_MUTATIONS } from "../replay/replayIntegrityModel.js";
import { command, type ControlCommandGroup } from "./commandRegistry.js";
import { array, bool, choice, empty, nullable, number, object, optional, text } from "./commandSchema.js";

export const trainingDraftPatch = object({
  name: optional(text(128)), sourceKind: optional(choice(e.source_kind)), startMode: optional(choice(e.start_mode)), randomScope: optional(choice(["RANGE", "MARKET"])),
  exchange: optional(text(96)), marketType: optional(text(96)), symbol: optional(text(96)), settlementAsset: optional(text(96)),
  baseInterval: optional(text(24)), displayInterval: optional(text(24)), requestedStartMs: optional(nullable(number(0, 1e15, true))),
  randomRangeStartMs: optional(nullable(number(0, 1e15, true))), randomRangeEndMs: optional(nullable(number(0, 1e15, true))),
  indicatorWarmupBars: optional(number(0, 1e6, true)), visibleHistoryMode: optional(choice(e.visible_history_mode)),
  visibleHistoryLookbackMs: optional(nullable(number(0, 1e15, true))), forwardCacheMs: optional(number(0, 1e15, true)),
  initialEquity: optional(text(64)), maxLeverage: optional(text(64)), makerFeeBps: optional(text(64)), takerFeeBps: optional(text(64)), marketSlippageBps: optional(text(64)),
  marginMode: optional(choice(e.margin_mode)), positionMode: optional(choice(e.position_mode)), fundingMode: optional(choice(e.funding_mode)),
  accountDataMode: optional(choice(e.account_data_mode)), fixedFundingRate: optional(text(64)), fundingIntervalMs: optional(number(1, 1e15, true)),
  bookMode: optional(choice(e.book_mode)), integrityMode: optional(choice(e.integrity_mode)), timeDisclosurePolicy: optional(choice(e.time_disclosure_policy)),
  allowedMutations: optional(array(choice(REPLAY_POLICY_MUTATIONS), 64)),
});
export function trainingHubCommands(runtime: TrainingHubRuntime): ControlCommandGroup {
  const { actions: a, ...snapshot } = runtime;
  const idle = () => !runtime.operation;
  return { id: "training-hub", title: "Replay training runs and setup", context: () => ({ filters: runtime.filters, draft: runtime.draft,
    runs: runtime.items.map((item) => [item.run_id, item.state]), operation: runtime.operation }), snapshot: () => snapshot, commands: [
      command("refresh", "Refresh training runs.", empty, () => a.refresh()),
      command("loadNext", "Load the next page of runs.", empty, () => a.loadNext(), { available: () => !!runtime.nextCursor && idle() }),
      command("filters", "Filter training runs.", object({ state: nullable(choice(e.run_state)), sourceKind: nullable(choice(e.source_kind)), compatibility: nullable(choice(["READY", "UNAVAILABLE"])) }), (filters) => a.setFilters(filters)),
      command("openCreate", "Load capabilities/catalog and open the run setup.", empty, () => a.openCreate(), { available: idle }),
      command("closeCreate", "Close run setup.", empty, () => a.closeCreate()),
      command("draft", "Edit known setup fields. Inspect evaluation.errors before creating; submission retains all existing capability/integrity checks.", trainingDraftPatch,
        (patch) => { if (!runtime.draft) throw new Error("DRAFT_UNAVAILABLE"); a.setDraft({ ...runtime.draft, ...patch }); }, { available: () => !!runtime.draft && idle() }),
      command("refreshCreatePlan", "Refresh the segment/data preparation plan.", empty, () => a.refreshCreatePlan(), { available: () => !!runtime.draft && idle() }),
      command("createRun", "Submit the inspected training draft through the existing setup workflow. Acknowledge before its automatic navigation; rediscover the replay group and inspect runId/viewer, or inspect hub.error on failure.", empty,
        () => { void Promise.resolve(a.createRun(runtime.draft!)).catch(() => undefined); return { submitted: true }; }, { available: () => !!runtime.draft && !!runtime.evaluation?.canSubmit && idle() }),
      command("deleteRun", "Delete a listed training run through the existing guarded backend action.", object({ runId: text(128) }), ({ runId }) => {
        if (!runtime.items.some((item) => item.run_id === runId)) throw new Error("RUN_UNAVAILABLE"); return a.deleteRun(runId);
      }, { available: idle }),
      command("continueRun", "Open an existing training run using its current resume action.", object({ runId: text(128) }), ({ runId }) => {
        const card = runtime.items.find((item) => item.run_id === runId); if (!card) throw new Error("RUN_UNAVAILABLE"); a.continueRun(card);
      }, { available: idle }),
      command("openStorage", "Load replay storage inventory.", empty, () => a.openStorage(), { available: idle }),
      command("refreshStorage", "Refresh replay storage inventory.", empty, () => a.refreshStorage(), { available: idle }),
      command("closeStorage", "Close storage inventory.", empty, () => a.closeStorage()),
      command("planStorageGc", "Create an inventory-bound storage GC plan. Inspect the plan before confirmation.", object({ protocol: choice(["replay.data.gc.v1", "replay.historical-book.gc.v1", "replay.account-history.gc.v1"]), targetReclaimBytes: number(0, 1e15, true), maxObjects: number(1, 10000, true) }), ({ protocol, targetReclaimBytes, maxObjects }) => a.planStorageGc(protocol, targetReclaimBytes, maxObjects), { available: () => runtime.storageOpen && idle() }),
      command("confirmStoragePlan", "Confirm/revoke the currently inspected GC plan; expectedContext binds this decision to the plan.", object({ confirmed: bool }), ({ confirmed }) => a.confirmStoragePlan(confirmed), { available: () => !!runtime.storagePlan && idle() }),
      command("runStorageGc", "Execute only the confirmed current plan. Existing generation/protection checks remain authoritative.", empty, () => a.runStorageGc(), { available: () => !!runtime.storagePlan && runtime.storagePlanConfirmed && idle() }),
      command("rehydrate", "Rehydrate a storage object using the existing backend authority checks.", object({ protocol: choice(["replay.data.gc.v1", "replay.historical-book.gc.v1", "replay.account-history.gc.v1"]), objectId: text(128) }), ({ protocol, objectId }) => a.rehydrateStorageObject(protocol, objectId), { available: () => runtime.storageOpen && idle() }),
    ] };
}
