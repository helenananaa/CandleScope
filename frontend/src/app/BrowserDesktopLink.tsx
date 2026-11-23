import { t } from "../i18n/index.js";
import { useLocale } from "../i18n/useLocale.js";

export const desktopReleaseUrl = "https://github.com/helenananaa/CandleScope/releases";

export function BrowserDesktopLink({ feature, className }: {
  feature?: "strategy" | "account";
  className?: string;
}) {
  useLocale();
  const label = t(feature === "strategy" ? "browser.desktop.runStrategies"
    : feature === "account" ? "browser.desktop.connectAccount" : "browser.desktop.download");
  return <a href={desktopReleaseUrl} className={className} target="_blank" rel="noreferrer">{label} ↗</a>;
}
