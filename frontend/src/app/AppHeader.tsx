import type { ReactNode } from "react";
import BrandMark, { BrandWordmark } from "../components/brand/BrandMark.js";
import { t } from "../i18n/index.js";
import HeaderActions, { type HeaderAction } from "./HeaderActions.js";
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
  return (
    <header
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
      <div className="app-header-main">
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
