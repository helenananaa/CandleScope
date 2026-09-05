import type { TrainingRunDraft } from "./trainingHubModel.js";
import type { ReplayCatalog } from "./replayTypes.js";

export function applyTrainingPreset(draft: TrainingRunDraft, mode: "practice" | "challenge", catalog?: ReplayCatalog | null): TrainingRunDraft {
  // A source switch loads a new catalog in TrainingHubLifecycle. Only reuse coverage for the same source.
  const ranges = draft.sourceKind === "BAR" ? catalog?.entries.flatMap((entry) => entry.eligible_ranges) ?? [] : [];
  const earliest = ranges.length ? Math.min(...ranges.map((range) => range.first_start_ms)) : null;
  const latest = ranges.length ? Math.max(...ranges.map((range) => range.last_start_ms)) : null;
  return { ...draft, sourceKind: "BAR", initialEquity: "10000", maxLeverage: "3", marginMode: "CROSS", positionMode: "ONE_WAY",
    integrityMode: mode === "challenge" ? "CHALLENGE" : "PRACTICE",
    startMode: mode === "challenge" ? "RANDOM" : "MANUAL",
    requestedStartMs: mode === "challenge" ? null : draft.requestedStartMs ?? latest,
    randomRangeStartMs: mode === "challenge" ? earliest : null, randomRangeEndMs: mode === "challenge" ? latest : null,
    timeDisclosurePolicy: mode === "challenge" ? "HIDE_ALL" : "NONE",
    allowedMutations: [], bookMode: "OFF", fundingMode: "OFF" };
}
