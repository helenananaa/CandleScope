import type { ChartAccountOverlaySettings } from "../chart-workspace/chartAccountOverlaySettings.js";

/** Only these historical text fields cross into the study view/control API.
 * Latest tags, links, plan metadata and images are not historical text facts. */
export interface StudyJournalNote {
  id: string; accountId: string; marketTimeMs: number; createdAtMs: number; savedAtMs: number;
  revision: number; fields: Record<string, string>; body: string; reviewNote: boolean; historyUnavailable: boolean;
  textUnavailable?: boolean;
}
export interface StudyJournalView {
  enabled: boolean; accountId: string | null; accountName: string | null; cursorMs: number; loading: boolean; error: string | null;
  hasMore: boolean;
  original: StudyJournalNote[]; reviews: StudyJournalNote[];
}

export interface StudyJournalFilters {
  noteSource: "all" | NonNullable<ChartAccountOverlaySettings["noteSource"]>;
  noteFilter: "all" | NonNullable<ChartAccountOverlaySettings["noteFilter"]>;
}

export interface StudyJournalData extends StudyJournalFilters {
  accountId: string; cursorMs: number; exchange: string; marketType: string; symbol: string;
  original: StudyJournalNote[]; reviews: StudyJournalNote[]; hasMore: boolean;
}
