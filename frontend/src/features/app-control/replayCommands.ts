import type { useReplayViewerRuntime, ReplayPhase3ControlType, ReplayPhase5TradeType } from "../replay/useReplayViewerRuntime.js";
import type { ReplayV2Json, ReplayOrderRequest } from "../replay/replayV2Types.js";
import { command, type ControlCommandGroup } from "./commandRegistry.js";
import { bool, choice, empty, object, optional, record, text } from "./commandSchema.js";

export function replayCommands(runId: string, viewer: ReturnType<typeof useReplayViewerRuntime>): ControlCommandGroup {
  const a = viewer.actions, v = viewer.viewerState;
  const available = () => v !== null && !viewer.loading;
  return { id: "replay", title: "Replay viewer, playback controller and simulated account", context: () => ({ runId, revision: v?.semantic_view_revision,
    track: v?.selected_track_id, interval: v?.display_interval }), snapshot: () => ({ runId, viewer: v,
      tracks: viewer.marketTracks, loading: viewer.loading, error: viewer.error, progress: viewer.progress, controlPending: viewer.controlPending?.type,
      viewerPending: viewer.viewerPending, summaryPreparing: viewer.summaryPreparing, summaryError: viewer.summaryError, periodSummary: viewer.periodSummary }), commands: [
    command("control", "Submit a playback/controller command through the existing replay authority protocol. Controller ownership and server revisions are still enforced.",
      object({ type: choice(["acquire_controller", "takeover_controller", "release_controller", "play", "pause", "set_speed", "step_event", "step_base", "step_display", "advance", "advance_by", "advance_to", "end"]), payload: optional(record) }),
      ({ type, payload }) => a.submitControl(type as ReplayPhase3ControlType, (payload ?? {}) as Record<string, ReplayV2Json>), { available }),
    command("cancelAdvance", "Cancel the current advance through the same replay control action.", empty, () => a.cancelAdvance(), { available, interrupt: true }),
    command("displayInterval", "Change the viewer display period.", object({ interval: text(24) }), ({ interval }) => a.setDisplayInterval(interval), { available }),
    command("selectTrack", "Select an existing market track.", object({ trackId: text(128) }), ({ trackId }) => a.selectTrack(trackId), { available }),
    command("addTrack", "Add a market track and optionally select it.", object({ exchange: text(96), marketType: text(96), symbol: text(96), displayInterval: optional(text(24)), select: optional(bool) }),
      ({ exchange, marketType, symbol, displayInterval, select }) => {
        const identity = { exchange, marketType, symbol, ...(displayInterval === undefined ? {} : { displayInterval }) };
        if (select) { if (!a.addAndSelectTrack) throw new Error("TRACK_SELECTION_UNAVAILABLE"); return a.addAndSelectTrack(identity); }
        if (!a.addTrack) throw new Error("TRACK_CREATION_UNAVAILABLE"); return a.addTrack(identity);
      }, { available }),
    command("subscriptionTier", "Change a replay market-track subscription tier.", object({ trackId: text(128), tier: choice(["NONE", "WARM", "FULL"]) }), ({ trackId, tier }) => a.setSubscriptionTier(trackId, tier), { available }),
    command("trade", "Submit a SIMULATED replay-account order/position command. This route has no live-exchange trading adapter.",
      object({ type: choice(["place_order", "replace_order", "cancel_order", "cancel_orders", "close_position", "execute_position_intent", "set_position_protection", "set_position_leverage", "allocate_isolated_margin"]), payload: record }),
      ({ type, payload }) => a.submitTrade(type as ReplayPhase5TradeType, payload as Record<string, ReplayV2Json>), { available }),
    command("previewOrder", "Preview a simulated replay order using the existing server contract.", object({ order: record, positionIntent: choice(["NET", "OPEN"]) }), ({ order, positionIntent }) => a.previewOrder(order as unknown as ReplayOrderRequest, positionIntent), { readOnly: true, available }),
    command("auditAccount", "Read the simulated account audit.", empty, () => a.auditAccount(), { readOnly: true, available }),
    command("resyncHistoricalBook", "Resync the historical order book.", empty, () => a.resyncHistoricalBook(), { available }),
    command("preparePeriodSummaries", "Prepare replay period summaries without revealing future data beyond the viewer contract.", empty, () => a.preparePeriodSummaries(), { available }),
    command("reload", "Reload replay viewer state.", empty, () => a.reload()),
  ] };
}
