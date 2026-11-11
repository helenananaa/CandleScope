import type { ChartAccountOverlaySettings } from "../chart-workspace/chartAccountOverlaySettings.js";
import type { JournalEntry } from "./tradingTypes.js";

export function filterJournalNoteMarkers(
  entries: readonly JournalEntry[],
  { noteSource, noteFilter }: Pick<ChartAccountOverlaySettings, "noteSource" | "noteFilter">,
  cursorMs = Number.POSITIVE_INFINITY,
): JournalEntry[] {
  return entries.filter(entry => {
    const review = entry.marketTimeMs !== null || entry.reviewNote;
    if ((noteSource === "original" && review) || (noteSource === "review" && !review)) return false;
    // Review supplements are presented as retrospective. Original notes can only
    // show associations or images that were available before the cursor.
    const cutoff = review ? Number.POSITIVE_INFINITY : cursorMs;
    if (noteFilter === "linked") {
      return entry.tradeId !== null && (entry.tradeLinkedAtMs ?? entry.updatedAtMs) < cutoff;
    }
    if (noteFilter === "screenshots") return entry.snapshots.some(snapshot => snapshot.hasImage && snapshot.createdAtMs < cutoff);
    return true;
  });
}
