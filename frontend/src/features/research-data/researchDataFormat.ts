import { getLocale, t } from "../../i18n/index.js";
import { LocalDataApiError } from "../local-data/localDataApi.js";
import { ResearchDataError } from "./researchDataSourceModel.js";

export function formatResearchRows(rows: number): string {
  return new Intl.NumberFormat(getLocale()).format(rows);
}

export function formatResearchDate(value: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString(getLocale());
}

/** A dataset quality status from the server, in the user's language; an unknown status stays as sent. */
export function formatQualityStatus(status: string): string {
  if (status === "accepted") return t("local.qualityStatus.accepted");
  if (status === "accepted_with_gaps") return t("local.qualityStatus.acceptedWithGaps");
  return status;
}

export function researchLibraryErrorMessage(reason: unknown): string {
  if (reason instanceof LocalDataApiError && reason.code === "local_profile_not_active") {
    return t("local.offlineMode");
  }
  if (reason instanceof ResearchDataError) return reason.action;
  return reason instanceof Error ? reason.message : t("local.opFailed");
}

export function waitResearchMs(milliseconds: number): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(resolve, milliseconds);
  });
}
