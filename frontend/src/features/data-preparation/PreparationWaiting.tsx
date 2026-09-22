import { t } from "../../i18n/index.js";
import { useLocale } from "../../i18n/useLocale.js";
import type { PreparationJob } from "./api.js";

export default function PreparationWaiting({ job }: { job: PreparationJob }) {
  const locale = useLocale();
  if (job.state !== "RUNNING" || job.waiting?.reason !== "RATE_LIMIT") return null;
  return <span role="status">{t("preparation.rateLimited", {
    time: new Date(job.waiting.retry_at_ms).toLocaleString(locale),
  })}</span>;
}
