import { t } from "../../i18n/index.js";
import type { WatchlistGroup } from "./watchlistTypes.js";

export function watchlistDisplayName(watchlist: Pick<WatchlistGroup, "id" | "name">): string {
  return watchlist.id === "default" && watchlist.name === "Watchlist"
    ? t("watchlist.title")
    : watchlist.name;
}
