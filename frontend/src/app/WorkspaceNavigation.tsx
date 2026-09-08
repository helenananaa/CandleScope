import { t } from "../i18n/index.js";

export default function WorkspaceNavigation({ active, offline = false, onReplay, replayDisabled = false, replayReason, researchEnabled = true }: {
  active: "live" | "research" | "replay";
  offline?: boolean;
  onReplay?: (() => void) | undefined;
  replayDisabled?: boolean;
  replayReason?: string | undefined;
  researchEnabled?: boolean;
}) {
  return <nav className="workspace-navigation" aria-label={t("ux.navigation")}>
    {offline ? <span aria-disabled="true">{t("ux.market")}</span> : <a href="/" aria-current={active === "live" ? "page" : undefined}>{t("ux.market")}</a>}
    {researchEnabled && <a href="/strategy.html" data-strategy-entry="enabled" data-backtest-entry="enabled" aria-current={active === "research" ? "page" : undefined}>{t("ux.research")}</a>}
    {offline || replayDisabled ? <button type="button" disabled title={replayReason}>{t("ux.training")}</button> : onReplay
      ? <button type="button" onClick={onReplay} data-replay-entry="enabled">{t("ux.training")}</button>
      : <a href="/replay.html" aria-current={active === "replay" ? "page" : undefined}>{t("ux.training")}</a>}
  </nav>;
}
