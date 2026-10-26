import type { ReactNode } from "react";
import { useSyncExternalStore } from "react";
import { ExtensionSlot } from "../features/extensions/ExtensionSlot.js";
import { getExtensionState, subscribeExtensions } from "../features/extensions/state.js";

export interface MarketWorkspaceFrameProps {
  toolbar: ReactNode;
  exportOverlay: ReactNode;
  chart: ReactNode;
  bottomPanel?: ReactNode;
  rightRail: ReactNode;
}

/** Source-neutral chart workspace slots; runtime ownership stays in callers. */
export default function MarketWorkspaceFrame({
  toolbar,
  exportOverlay,
  chart,
  bottomPanel = null,
  rightRail,
}: MarketWorkspaceFrameProps) {
  const extension = useSyncExternalStore(subscribeExtensions, getExtensionState, getExtensionState);
  const order = extension.layout?.workspace;
  const position = (name: string) => order?.indexOf(name) ?? 0;
  return (
    <div className="main-content-area">
      <div className="chart-with-toolbar" style={order ? { order: position("chart"), flexDirection: position("toolbar") > position("chart") ? "row-reverse" : "row" } : undefined}>
        <ExtensionSlot name="toolbar">{toolbar}</ExtensionSlot>
        <div className="market-workspace-content">
          <ExtensionSlot name="exportOverlay">{exportOverlay}</ExtensionSlot>
          <div className="extension-chart-slot" style={{ display: "flex", flex: 1, minHeight: 0, minWidth: 0, order: position("chart") }}><ExtensionSlot name="chart">{chart}</ExtensionSlot></div>
          <div className="extension-bottom-slot" style={{ order: position("bottomPanel") }}><ExtensionSlot name="bottomPanel">{bottomPanel}</ExtensionSlot></div>
        </div>
      </div>
      <div className="extension-rail-slot" data-extension-rail-side={order && position("rightRail") < position("chart") ? "left" : "right"} style={{ order: position("rightRail") }}><ExtensionSlot name="rightRail">{rightRail}</ExtensionSlot></div>
    </div>
  );
}
