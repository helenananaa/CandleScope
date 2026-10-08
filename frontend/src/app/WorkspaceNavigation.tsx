import { useEffect } from "react";
import { t } from "../i18n/index.js";

/**
 * Each workspace is its own HTML entry, so switching is a page load. Chromium
 * prerenders a linked entry when the pointer rests on its link, which makes the
 * switch near-instant. Only research and replay are listed: prerendering the
 * market page would open live market streams in the background.
 */
function usePrerenderOnHover(urls: readonly string[]): void {
  const key = urls.join("|");
  useEffect(() => {
    if (!key || typeof document === "undefined") return undefined;
    if (typeof HTMLScriptElement === "undefined" || !HTMLScriptElement.supports?.("speculationrules")) return undefined;
    const script = document.createElement("script");
    script.type = "speculationrules";
    script.textContent = JSON.stringify({
      prerender: [{ source: "list", urls: key.split("|"), eagerness: "moderate" }],
    });
    document.head.append(script);
    return () => script.remove();
  }, [key]);
}

export default function WorkspaceNavigation({ active, offline = false, onReplay, replayDisabled = false, replayReason, researchEnabled = true }: {
  active: "live" | "research" | "replay";
  offline?: boolean;
  onReplay?: (() => void) | undefined;
  replayDisabled?: boolean;
  replayReason?: string | undefined;
  researchEnabled?: boolean;
}) {
  const prerenderable: string[] = [];
  if (researchEnabled && active !== "research") prerenderable.push("/strategy.html");
  if (!offline && !replayDisabled && !onReplay && active !== "replay") prerenderable.push("/replay.html");
  usePrerenderOnHover(prerenderable);
  return <nav className="workspace-navigation" aria-label={t("ux.navigation")}>
    {offline ? <span aria-disabled="true">{t("ux.market")}</span> : <a href="/" aria-current={active === "live" ? "page" : undefined}>{t("ux.market")}</a>}
    {researchEnabled && <a href="/strategy.html" data-strategy-entry="enabled" data-backtest-entry="enabled" aria-current={active === "research" ? "page" : undefined}>{t("ux.research")}</a>}
    {offline || replayDisabled ? <button type="button" disabled title={replayReason}>{t("ux.training")}</button> : onReplay
      ? <button type="button" onClick={onReplay} data-replay-entry="enabled">{t("ux.training")}</button>
      : <a href="/replay.html" aria-current={active === "replay" ? "page" : undefined}>{t("ux.training")}</a>}
  </nav>;
}
