import { createContext, useContext, type ReactNode } from "react";
import { createPortal } from "react-dom";

export type StrategyDockSlotName = "tabs" | "actions" | "notice";
export type StrategyDockSlotTargets = Partial<Record<StrategyDockSlotName, HTMLElement | null>>;

const SlotsContext = createContext<StrategyDockSlotTargets | null>(null);
const VisibleContext = createContext(true);

export const StrategyDockSlotsProvider = SlotsContext.Provider;

/** A pane that stays mounted while hidden. Only the visible pane publishes dock chrome. */
export function StrategyDockPane({ hidden, children }: { hidden: boolean; children: ReactNode }) {
  const parentVisible = useContext(VisibleContext);
  return <div className="strategy-mode-pane" hidden={hidden}>
    <VisibleContext.Provider value={parentVisible && !hidden}>{children}</VisibleContext.Provider>
  </div>;
}

/** Renders pane chrome into the dock header; outside a dock it renders in place. */
export function StrategyDockSlot({ name, children }: { name: StrategyDockSlotName; children: ReactNode }) {
  const slots = useContext(SlotsContext);
  const visible = useContext(VisibleContext);
  if (!slots) return <>{children}</>;
  const target = slots[name];
  return visible && target ? createPortal(children, target) : null;
}
