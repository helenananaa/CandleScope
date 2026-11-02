import type { MarketSeries } from "../market-data/marketDataTypes.js";

export interface StudyBar extends Record<string, unknown> {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  closeTimeMs: number;
  is_closed: true;
}
export interface HistoryStudy {
  id: string;
  series: MarketSeries;
  capturedAtMs: number;
  inputKind: "captured-market-history";
  rows: readonly StudyBar[];
}
export interface HistoryStudyView {
  revision: number;
  active: boolean;
  cursorMs: number | null;
  study: HistoryStudy | null;
}
export interface HistoryStudyCursor { studyId: string; revision: number; active: boolean; cursorMs: number }
export interface StudyNote {
  id: string;
  fields: Record<string, string>;
  revisionCount: number;
  marketTimeMs: number;
  createdAtMs: number;
  updatedAtMs: number;
  reviewNote: true;
  revisions: { revision: number; savedAtMs: number; fields: Record<string, string> }[];
}
export interface SavedStudySummary {
  id: string; series: MarketSeries; capturedAtMs: number; cursorMs: number; firstMs: number; lastMs: number;
}
