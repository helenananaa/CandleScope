import type { ReactNode } from "react";
import MarketTopBarFrame from "./MarketTopBarFrame.js";

/**
 * App header + scrolling body for pages without a chart workspace
 * (replay home, replay status screens, market picker), so every page
 * keeps the same brand and workspace navigation.
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
  return (
    <div className="app-page">
      <MarketTopBarFrame source={source} className="app-page-top-bar" trailing={trailing} />
      <div className="app-page-body">{children}</div>
    </div>
  );
}
