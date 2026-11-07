import { t } from "../../i18n/index.js";
import { describeError } from "../../i18n/serverErrors.js";
import { ResearchReturnUnsupported } from "./researchSelectedVersion.js";
export function researchReturnError(error: unknown): string {
  return error instanceof ResearchReturnUnsupported ? t("researchReturn.unsupported", { field: error.field }) : describeError(error, t("serverError.generic"));
}
