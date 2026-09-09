import { memo } from "react";
import { ReplayPaperTradingDock, type ReplayRightRailProps } from "./ReplayRightRail.js";
export default memo(ReplayPaperTradingDock);
export type ReplayPaperTradingDockProps = Pick<ReplayRightRailProps, "runtime" | "viewer">;
