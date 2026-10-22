import type { ReplayIntegrityRuntime } from "../replay/useReplayIntegrityRuntime.js";
import { buildReplayTrainingReportExport, replayTrainingReportToCsv } from "../replay/replayReportExport.js";
import { command, type ControlCommandGroup } from "./commandRegistry.js";
import { choice, empty, nullable, number, object, optional, text } from "./commandSchema.js";
import { publishControlFile } from "./controlFiles.js";

export function replayIntegrityCommands(runtime: ReplayIntegrityRuntime): ControlCommandGroup {
  const { actions: a } = runtime;
  const idle = () => !!runtime.runId && !runtime.operation && !runtime.review;
  return { id: "replay-integrity", title: "Replay rules, integrity, review and reports", context: () => ({ runId: runtime.runId, rules: runtime.rules, reviewId: runtime.review?.review_id, operation: runtime.operation }),
    snapshot: () => ({ runId: runtime.runId, rules: runtime.rules, integrity: runtime.integrity, equity: runtime.equity, reportAvailable: !!runtime.report, review: runtime.review, budget: runtime.budget, operation: runtime.operation, error: runtime.error, forked: runtime.forked }), commands: [
      command("refresh", "Refresh public integrity/rules/account/report state.", empty, () => a.refresh()),
      command("deposit", "Apply a simulated-account deposit under the current replay policy.", object({ amount: text(64), reason: text(512) }), ({ amount, reason }) => a.deposit(amount, reason), { available: idle }),
      command("withdraw", "Apply a simulated-account withdrawal under the current replay policy.", object({ amount: text(64), reason: text(512) }), ({ amount, reason }) => a.withdraw(amount, reason), { available: idle }),
      command("revealTime", "Request time disclosure using the existing policy command; challenge mode/server guards remain authoritative.", object({ reason: text(512) }), ({ reason }) => a.revealTime(reason), { available: idle }),
      command("fees", "Change fee policy under the current replay rules.", object({ makerFeeBps: text(64), takerFeeBps: text(64), reason: text(512) }), ({ makerFeeBps, takerFeeBps, reason }) => a.changeFeePolicy(makerFeeBps, takerFeeBps, reason), { available: idle }),
      command("leverageCap", "Change the simulated-account leverage cap under replay policy.", object({ maxLeverage: text(64), reason: text(512) }), ({ maxLeverage, reason }) => a.changeLeverageCap(maxLeverage, reason), { available: idle }),
      command("funding", "Change replay funding policy.", object({ mode: choice(["OFF", "SANDBOX_FIXED"]), fixedRate: nullable(text(64)), intervalMs: nullable(number(1, 1e15, true)), reason: text(512) }), ({ mode, fixedRate, intervalMs, reason }) => a.changeFundingPolicy(mode, fixedRate, intervalMs, reason), { available: idle }),
      command("marker", "Record a training marker through the integrity event writer.", object({ text: text(2048) }), ({ text }) => a.addMarker(text), { available: idle }),
      command("startReview", "Open a recorded review projection; does not expose future simulation internals.", object({ eventId: optional(nullable(text(128))) }), ({ eventId }) => a.startReview(eventId), { available: () => !!runtime.runId && !runtime.operation }),
      command("reviewControl", "Control the recorded review projection.", object({ action: choice(["JUMP", "PREVIOUS", "NEXT", "PLAY", "PAUSE"]), eventId: optional(nullable(text(128))), playbackRate: optional(nullable(choice(["0.25", "0.5", "1", "2", "4", "8"]))) }), ({ action, ...options }) => a.controlReview(action, options), { available: () => !!runtime.review && !runtime.operation }),
      command("closeReview", "Close review.", empty, () => a.closeReview()),
      command("forkReview", "Fork the inspected recorded event using the existing policy checks.", object({ eventId: text(128) }), ({ eventId }) => a.forkReview(eventId), { available: () => !!runtime.review && !runtime.operation }),
      command("exportReport", "Export the public training report to JSON/CSV. Existing disclosure filtering is retained.", object({ format: choice(["json", "csv"]) }), ({ format }) => {
        if (!runtime.report) throw new Error("REPORT_UNAVAILABLE");
        const content = format === "json" ? JSON.stringify(buildReplayTrainingReportExport(runtime.report)) : replayTrainingReportToCsv(runtime.report);
        return publishControlFile(new Blob([content], { type: format === "json" ? "application/json" : "text/csv" }), `replay-report.${format}`);
      }, { available: () => !!runtime.report }),
    ] };
}
