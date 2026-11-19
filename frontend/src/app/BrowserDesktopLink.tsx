import { useLocale } from "../i18n/useLocale.js";

export const desktopReleaseUrl = "https://github.com/helenananaa/CandleScope/releases";

export function BrowserDesktopLink({ feature, className }: {
  feature?: "strategy" | "account";
  className?: string;
}) {
  const chinese = useLocale().startsWith("zh");
  const label = feature === "strategy"
    ? (chinese ? "下载桌面版运行策略" : "Download the desktop app to run strategies")
    : feature === "account"
      ? (chinese ? "下载桌面版连接交易所账户" : "Download the desktop app to connect an exchange account")
      : (chinese ? "下载桌面版" : "Download the desktop app");
  return <a href={desktopReleaseUrl} className={className} target="_blank" rel="noreferrer">{label} ↗</a>;
}
