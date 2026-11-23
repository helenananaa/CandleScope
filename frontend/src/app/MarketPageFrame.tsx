import type { ReactNode, Ref } from "react";
import { useSyncExternalStore } from "react";
import { ExtensionSlot } from "../features/extensions/ExtensionSlot.js";
import { getExtensionState, subscribeExtensions } from "../features/extensions/state.js";
import SkipToChart from "./SkipToChart.js";

export interface MarketPageFrameProps {
  rootRef?: Ref<HTMLDivElement>;
  topBar: ReactNode;
  intervalSelector: ReactNode;
  workspace: ReactNode;
  featureSurfaces: ReactNode;
  statusBar: ReactNode;
  /** A "skip to chart" control as the first Tab stop (pages whose workspace is a chart). */
  skipToChart?: boolean;
}

/** Source-neutral outer market-page layout. */
export default function MarketPageFrame({
  rootRef,
  topBar,
  intervalSelector,
  workspace,
  featureSurfaces,
  statusBar,
  skipToChart = false,
}: MarketPageFrameProps) {
  const extension = useSyncExternalStore(subscribeExtensions, getExtensionState, getExtensionState);
  const slots: Record<string, ReactNode> = { topBar, intervalSelector, workspace, featureSurfaces, statusBar };
  const order = extension.layout?.page ?? ["topBar", "intervalSelector", "workspace", "featureSurfaces", "statusBar"];
  return (
    <div className="app-layout" ref={rootRef}>
      {skipToChart ? <SkipToChart /> : null}
      <ExtensionSlot name="shell" slots={slots}>
        {order.map((name) => <ExtensionSlot key={name} name={name}>{slots[name]}</ExtensionSlot>)}
      </ExtensionSlot>
    </div>
  );
}
