import type { ReactNode } from "react";

/**
 * A research view's interval bar (`top`) above its workspace. The mode rail that sat beside them is
 * gone (ADR-BACKTEST-015 P5c4): the research tools are fields of the one workspace.
 */
export function ResearchModeLayout({ top = null, children }: { top?: ReactNode; children: ReactNode }) {
  return <>{top}{children}</>;
}
