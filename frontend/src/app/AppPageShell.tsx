import { useContext, useState } from "react";
import type { ReactNode } from "react";
import MarketTopBarFrame from "./MarketTopBarFrame.js";
import { CapabilityRailIcon } from "./marketRailIcons.js";
import PageSettingsDialog from "./PageSettingsDialog.js";
import { t } from "../i18n/index.js";
import { PageSettingsContext } from "./pageSettingsContext.js";

/**
 * App header + scrolling body for pages without a chart workspace
 * (replay home, replay status screens, market picker), so every page
 * keeps the same brand, workspace navigation and Settings entry.
 */
export default function AppPageShell({
  source,
  trailing,
  children,
}: {
  source: "live" | "replay" | "research";
  trailing?: ReactNode;
  children: ReactNode;
}) {
  const settingsRuntime = useContext(PageSettingsContext);
  const [settingsOpen, setSettingsOpen] = useState(false);
  return (
    <div className="app-page">
      <MarketTopBarFrame
        source={source}
        className="app-page-top-bar"
        trailing={(
          <>
            {trailing}
            {settingsRuntime && (
              <button
                type="button"
                className="settings-btn indicator-toggle-btn"
                onClick={() => setSettingsOpen(true)}
                title={t("shell.settings")}
                aria-label={t("shell.settings")}
              >
                <span aria-hidden="true" style={{ display: "flex" }}><CapabilityRailIcon /></span>
              </button>
            )}
          </>
        )}
      />
      <div className="app-page-body">{children}</div>
      {settingsRuntime && settingsOpen && (
        <PageSettingsDialog runtime={settingsRuntime} onClose={() => setSettingsOpen(false)} />
      )}
    </div>
  );
}
