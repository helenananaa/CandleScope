import { Component, useSyncExternalStore } from "react";
import type { ReactNode } from "react";
import { getExtensionState, subscribeExtensions } from "./state.js";
import type { ExtensionSlot as SlotComponent } from "./contracts.js";

const componentIds = new WeakMap<SlotComponent, number>();
let nextComponentId = 0;

class SlotBoundary extends Component<{ children: ReactNode; fallback: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidCatch(error: Error) { console.error("Trusted extension component failed", error); }
  render() { return this.state.failed ? this.props.fallback : this.props.children; }
}

export function ExtensionSlot({ name, children, slots }: { name: string; children: ReactNode; slots?: Record<string, ReactNode> }) {
  const state = useSyncExternalStore(subscribeExtensions, getExtensionState, getExtensionState);
  const Replacement = state.slots.get(name);
  if (Replacement && !componentIds.has(Replacement)) componentIds.set(Replacement, ++nextComponentId);
  return Replacement ? <SlotBoundary key={`${name}:${Replacement ? componentIds.get(Replacement) : 0}`} fallback={children}>
    <Replacement fallback={children} {...(slots ? { slots } : {})} />
  </SlotBoundary> : children;
}
