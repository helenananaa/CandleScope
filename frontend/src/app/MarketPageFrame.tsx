import type { ReactNode, Ref } from "react";
import { useSyncExternalStore } from "react";
import { ExtensionSlot } from "../features/extensions/ExtensionSlot.js";
import { getExtensionState, subscribeExtensions } from "../features/extensions/state.js";

export interface MarketPageFrameProps {
  rootRef?: Ref<HTMLDivElement>;
  topBar: ReactNode;
  intervalSelector: ReactNode;
  workspace: ReactNode;
  featureSurfaces: ReactNode;
  statusBar: ReactNode;
}

/** Source-neutral outer market-page layout. */
export default function MarketPageFrame({
  rootRef,
  topBar,
  intervalSelector,
  workspace,
  featureSurfaces,
  statusBar,
}: MarketPageFrameProps) {
  const extension = useSyncExternalStore(subscribeExtensions, getExtensionState, getExtensionState);
  const slots: Record<string, ReactNode> = { topBar, intervalSelector, workspace, featureSurfaces, statusBar };
  const order = extension.layout?.page ?? ["topBar", "intervalSelector", "workspace", "featureSurfaces", "statusBar"];
  return (
    <div className="app-layout" ref={rootRef}>
      <ExtensionSlot name="shell" slots={slots}>
        {order.map((name) => <ExtensionSlot key={name} name={name}>{slots[name]}</ExtensionSlot>)}
      </ExtensionSlot>
    </div>
  );
}
