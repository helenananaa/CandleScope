import { memo } from "react";
import { ReplayTradingWorkbench, type ReplayRightRailProps } from "./ReplayRightRail.js";
export default memo(ReplayTradingWorkbench);
export type ReplayTradingWorkbenchProps = Pick<ReplayRightRailProps, "runtime" | "viewer" | "formatTime">;
