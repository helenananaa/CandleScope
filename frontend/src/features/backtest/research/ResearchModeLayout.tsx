import { useContext, type ReactNode } from "react";
import { ResearchModeRailContext } from "./researchModeRailContext.js";

/**
 * Puts the page's mode rail at the left edge, from under the header down, beside the view's
 * interval bar (`top`) and workspace, so the rail keeps its place in every mode.
 */
export function ResearchModeLayout({ top = null, children }: { top?: ReactNode; children: ReactNode }) {
  const rail = useContext(ResearchModeRailContext);
  if (rail === null || rail === undefined) return <>{top}{children}</>;
  return (
    <div className="research-mode-layout">
      {rail}
      <div className="research-mode-body">{top}{children}</div>
    </div>
  );
}
