import { t } from "../../i18n/index.js";

export function snapshotDeliveryLabel(
  mode: "partial" | "full",
  snapshotMode: "live_snapshot" | "polling_snapshot" | null,
  source?: string,
): string {
  if (mode === "full") return t("orderBook.delivery.strictContinuous");
  if (source === "http") return t("orderBook.delivery.pollingSnapshot");
  if (source === "websocket") return t("orderBook.delivery.liveSnapshot");
  return snapshotMode === "polling_snapshot"
    ? t("orderBook.delivery.pollingSnapshot")
    : t("orderBook.delivery.liveSnapshot");
}
