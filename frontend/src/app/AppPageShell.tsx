import { useContext, useState } from "react";
import type { ReactNode } from "react";
import AppHeader from "./AppHeader.js";
import PageSettingsDialog from "./PageSettingsDialog.js";
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
  /** Inline controls at the right of the header. */
  trailing?: ReactNode;
  children: ReactNode;
}) {
  const settingsRuntime = useContext(PageSettingsContext);
  const [settingsOpen, setSettingsOpen] = useState(false);
  return (
    <div className="app-page">
      <AppHeader
        source={source}
        extras={trailing}
        {...(settingsRuntime ? { settings: { onOpen: () => setSettingsOpen(true) } } : {})}
      />
      <div className="app-page-body">{children}</div>
      {settingsRuntime && settingsOpen && (
        <PageSettingsDialog runtime={settingsRuntime} onClose={() => setSettingsOpen(false)} />
      )}
    </div>
  );
}
