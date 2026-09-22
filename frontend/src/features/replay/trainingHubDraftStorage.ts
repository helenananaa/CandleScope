import { createTrainingRunDraft, type TrainingRunDraft } from "./trainingHubModel.js";
import { REPLAY_V2_ENUMS, type ReplayLaunchContext } from "./replayV2Types.js";
import { REPLAY_POLICY_MUTATIONS } from "./replayIntegrityModel.js";

export type HubDraftStorage = Pick<Storage, "getItem" | "setItem">;
export interface StoredHubDraft {
  draft: TrainingRunDraft;
  submission: { identity: string; key: string } | null;
}

export function defaultHubDraftStorage(): HubDraftStorage | null {
  try { return typeof window === "undefined" ? null : window.localStorage; } catch { return null; }
}

export function hubDraftKey(context?: ReplayLaunchContext): string {
  return `candlescope.replay-create.v1:${context
    ? JSON.stringify([context.exchange, context.market_type, context.symbol, context.display_interval]) : "hub"}`;
}

const enums: Partial<Record<keyof TrainingRunDraft, readonly string[]>> = {
  sourceKind: REPLAY_V2_ENUMS.source_kind, startMode: REPLAY_V2_ENUMS.start_mode,
  visibleHistoryMode: REPLAY_V2_ENUMS.visible_history_mode, marginMode: REPLAY_V2_ENUMS.margin_mode,
  positionMode: REPLAY_V2_ENUMS.position_mode, fundingMode: REPLAY_V2_ENUMS.funding_mode,
  accountDataMode: REPLAY_V2_ENUMS.account_data_mode, bookMode: REPLAY_V2_ENUMS.book_mode,
  integrityMode: REPLAY_V2_ENUMS.integrity_mode, timeDisclosurePolicy: REPLAY_V2_ENUMS.time_disclosure_policy,
};

export function readHubDraft(storage: HubDraftStorage | null, key: string): StoredHubDraft | null {
  try {
    const text = storage?.getItem(key);
    if (!text || text.length > 300_000) return null;
    const value: unknown = JSON.parse(text);
    if (!value || typeof value !== "object" || !("version" in value) || value.version !== 1
      || !("draft" in value) || !value.draft || typeof value.draft !== "object") return null;
    const raw = value.draft as Record<string, unknown>;
    const draft = createTrainingRunDraft();
    for (const field of Object.keys(draft) as Array<keyof TrainingRunDraft>) {
      const item = raw[field];
      const base = draft[field];
      if (field === "allowedMutations") {
        if (!Array.isArray(item) || item.length > REPLAY_POLICY_MUTATIONS.length
          || item.some((entry: unknown) => typeof entry !== "string" || !(REPLAY_POLICY_MUTATIONS as readonly string[]).includes(entry))) return null;
      } else if (enums[field]) {
        if (typeof item !== "string" || !enums[field]!.includes(item)) return null;
      } else if (typeof base === "string") {
        if (typeof item !== "string" || item.length > 4096) return null;
      } else if (!(["requestedStartMs", "randomRangeStartMs", "randomRangeEndMs", "visibleHistoryLookbackMs"].includes(field) && item === null)
        && (typeof item !== "number" || !Number.isSafeInteger(item))) {
        return null;
      }
      // Restore only known fields; semantic validation still uses current capabilities.
      Object.assign(draft, { [field]: item });
    }
    let submission: StoredHubDraft["submission"] = null;
    if ("submission" in value && value.submission && typeof value.submission === "object") {
      const saved = value.submission;
      if ("identity" in saved && typeof saved.identity === "string" && saved.identity.length <= 256_000
        && "key" in saved && typeof saved.key === "string" && /^[a-zA-Z0-9_-]{8,128}$/.test(saved.key)) {
        submission = { identity: saved.identity, key: saved.key };
      }
    }
    return { draft, submission };
  } catch { return null; }
}

export function writeHubDraft(storage: HubDraftStorage | null, key: string, value: StoredHubDraft): void {
  try { storage?.setItem(key, JSON.stringify({ version: 1, ...value })); } catch { /* Storage restrictions must not prevent replay. */ }
}
