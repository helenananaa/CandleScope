import { useLayoutEffect, useRef, type ReactNode, type RefObject } from "react";
import BrandMark, { BrandWordmark } from "../components/brand/BrandMark.js";
import { t } from "../i18n/index.js";
import HeaderActions, { type HeaderAction } from "./HeaderActions.js";
import { chooseHeaderCompaction } from "./headerActionsModel.js";
import { CapabilityRailIcon } from "./marketRailIcons.js";
import WorkspaceNavigation from "./WorkspaceNavigation.js";

export type { HeaderAction } from "./HeaderActions.js";

export interface AppHeaderSettings {
  onOpen(): void;
  /** Starts loading the Settings code when the pointer or focus reaches the button. */
  onPrepare?(): void;
}

export interface AppHeaderProps {
  readonly source?: "live" | "replay" | "local" | "research";
  readonly className?: string;
  readonly brandIcon?: ReactNode;
  readonly brandText?: ReactNode;
  /** Workspace navigation; the three workspaces by default. */
  readonly navigation?: ReactNode;
  readonly offline?: boolean;
  /** The page's mode or a way back within it, right after the navigation. */
  readonly badge?: ReactNode;
  /** What the page is about: the symbol, the data source or the replay run. */
  readonly context?: ReactNode;
  /** Controls for that context: intervals, prices, chart source. They give way at narrow widths through their own rules. */
  readonly tools?: ReactNode;
  /** Controls that stay inline at the right, after the actions (layout picker, plugin toolbar). */
  readonly extras?: ReactNode;
  /** Page actions at the right. Those that do not fit move into the 更多 menu, last first. */
  readonly actions?: readonly HeaderAction[];
  /** Panel toggles (indicators, alerts), just before Settings. */
  readonly panels?: ReactNode;
  /** Settings, always the last control on the right. */
  readonly settings?: AppHeaderSettings;
}

/**
 * The header every page shares: brand and workspace navigation, the page's context and tools on
 * the left, its actions, panels and Settings on the right. Page actions collapse into a menu when
 * space runs out, so the context and Settings never move.
 */
export default function AppHeader({
  source = "live",
  className = "",
  brandIcon,
  brandText,
  navigation,
  offline = false,
  badge = null,
  context = null,
  tools = null,
  extras = null,
  actions = [],
  panels = null,
  settings,
}: AppHeaderProps) {
  const headerRef = useRef<HTMLElement>(null);
  const mainRef = useRef<HTMLDivElement>(null);
  useHeaderCompaction(headerRef, mainRef);
  return (
    <header
      ref={headerRef}
      className={`top-bar app-header ${className}`.trim()}
      id="top-bar"
      data-runtime-source={source}
      data-market-shell-owner="top-bar"
    >
      <div className="logo">
        <div className="logo-icon">
          {brandIcon === undefined ? <BrandMark size={24} /> : brandIcon}
        </div>
        {brandText === undefined
          ? <BrandWordmark />
          : <span className="logo-text">{brandText}</span>}
      </div>
      {navigation === undefined ? <WorkspaceNavigation active={source === "live" ? "live" : source === "replay" ? "replay" : "research"} offline={offline} /> : navigation}
      {badge}
      <div ref={mainRef} className="app-header-main">
        {context}
        {tools}
      </div>
      <div className="app-header-end">
        <HeaderActions actions={actions} />
        {extras}
        {panels ? <div className="app-header-panels">{panels}</div> : null}
        {settings ? (
          <button
            type="button"
            className="settings-btn indicator-toggle-btn"
            title={t("shell.settings")}
            aria-label={t("shell.settings")}
            onPointerEnter={settings.onPrepare}
            onFocus={settings.onPrepare}
            onClick={settings.onOpen}
          >
            <span aria-hidden="true" className="app-header-icon"><CapabilityRailIcon /></span>
          </button>
        ) : null}
      </div>
    </header>
  );
}

/**
 * Sets data-compact on the header to the steps it needs to fit ("1 2 3"), measured rather than tied
 * to the window width, so it holds in every language. Rules for each step are in topBar.css.
 */
function useHeaderCompaction(headerRef: RefObject<HTMLElement | null>, mainRef: RefObject<HTMLDivElement | null>): void {
  useLayoutEffect(() => {
    const header = headerRef.current;
    const main = mainRef.current;
    if (!header || !main || typeof ResizeObserver === "undefined") return undefined;
    const apply = (level: number) => {
      header.dataset.compact = Array.from({ length: level }, (_, index) => String(index + 1)).join(" ");
    };
    const actionsFit = () => {
      const container = header.querySelector<HTMLElement>(".app-header-actions");
      if (!container) return true;
      const items = [...container.querySelectorAll<HTMLElement>("[data-header-action]")];
      const gap = Number.parseFloat(getComputedStyle(container).columnGap) || 0;
      const needed = items.reduce((sum, item) => sum + item.offsetWidth, 0) + gap * Math.max(0, items.length - 1);
      return needed <= container.clientWidth;
    };
    let frame = 0;
    let level = 0;
    let fromScratch = true;
    const fit = () => {
      frame = 0;
      level = chooseHeaderCompaction(apply, {
        mainOverflows: () => mainNeeds(main) > main.clientWidth + 1,
        actionsFit,
      }, fromScratch ? 0 : level);
      fromScratch = false;
    };
    const schedule = (scratch: boolean) => {
      fromScratch ||= scratch;
      if (!frame) frame = requestAnimationFrame(fit);
    };
    fit();
    // A resize recomputes from scratch; a content change (a longer symbol, a ticking price, an
    // attached strategy) may only add steps.
    let lastWidth = header.clientWidth;
    const resize = new ResizeObserver(() => {
      if (header.clientWidth === lastWidth) return;
      lastWidth = header.clientWidth;
      schedule(true);
    });
    resize.observe(header);
    const mutation = new MutationObserver(() => schedule(false));
    mutation.observe(header, { childList: true, subtree: true, characterData: true });
    // Widths change when the interface font finishes loading.
    let active = true;
    void document.fonts?.ready.then(() => { if (active) schedule(true); });
    return () => { active = false; resize.disconnect(); mutation.disconnect(); if (frame) cancelAnimationFrame(frame); };
  }, [headerRef, mainRef]);
}

/** Width the left side needs: its items do not shrink before the last step, so their widths are their natural ones. */
function mainNeeds(main: HTMLElement): number {
  const items = [...main.children].filter((item): item is HTMLElement => item instanceof HTMLElement && item.offsetParent !== null);
  const gap = Number.parseFloat(getComputedStyle(main).columnGap) || 0;
  return items.reduce((sum, item) => sum + item.offsetWidth, 0) + gap * Math.max(0, items.length - 1);
}
