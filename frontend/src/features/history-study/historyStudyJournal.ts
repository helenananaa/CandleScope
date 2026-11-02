/** Only these historical text fields cross into the study view/control API.
 * Latest tags, links, plan metadata and images are not historical text facts. */
export interface StudyJournalNote {
  id: string; accountId: string; marketTimeMs: number; createdAtMs: number; savedAtMs: number;
  revision: number; fields: Record<string, string>; body: string; reviewNote: boolean; historyUnavailable: boolean;
}
export interface StudyJournalView {
  enabled: boolean; accountId: string | null; accountName: string | null; cursorMs: number; loading: boolean; error: string | null;
  hasMore: boolean;
  original: StudyJournalNote[]; reviews: StudyJournalNote[];
}

export interface StudyJournalData {
  accountId: string; cursorMs: number; original: StudyJournalNote[]; reviews: StudyJournalNote[]; hasMore: boolean;
}
