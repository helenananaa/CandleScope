// The overlay stack: which drawers, modals and popovers are open, in what order.
// Rules (DESIGN.md, design refactor plan §5): one drawer per side (opening another replaces it),
// modals always above drawers, popovers above the layer that opened them, Escape closes the
// topmost layer that allows it. Pure: the DOM side lives in overlayRuntime.ts.

export type OverlayKind = "drawer" | "modal" | "popover";
export type DrawerSide = "left" | "right";

export interface OverlayEntry {
  id: string;
  kind: OverlayKind;
  /** Drawers only. */
  side?: DrawerSide;
  /** Called when the stack closes this layer (Escape, or replaced by another drawer). */
  requestClose: () => void;
  /** False for layers that must stay until the user decides (a running task). Default true. */
  closeOnEscape?: boolean;
}

/** Stacking bands, lowest first. Matches the --z-* tokens: overlay < modal < menu. */
const BAND: Record<OverlayKind, number> = { drawer: 0, modal: 1, popover: 2 };
export const BAND_BASE: Record<OverlayKind, number> = { drawer: 500, modal: 1000, popover: 10000 };

export interface OverlayStack {
  /** Adds a layer and returns the layers it replaces; the caller asks those to close. */
  open(entry: OverlayEntry): OverlayEntry[];
  close(id: string): void;
  /** Layers from bottom to top. */
  layers(): OverlayEntry[];
  top(): OverlayEntry | undefined;
  /** Closes the topmost layer that allows Escape. Returns whether one was closed. */
  escape(): boolean;
  zIndex(id: string): number | undefined;
  /** Layers that must not take input because a modal sits above them. */
  inert(id: string): boolean;
  hasModal(): boolean;
  subscribe(listener: () => void): () => void;
}

export function createOverlayStack(): OverlayStack {
  // Open order; layers() sorts by band and keeps open order within a band.
  let entries: OverlayEntry[] = [];
  const listeners = new Set<() => void>();
  const notify = () => { for (const listener of [...listeners]) listener(); };
  const ordered = () => entries
    .map((entry, index) => ({ entry, index }))
    .sort((a, b) => BAND[a.entry.kind] - BAND[b.entry.kind] || a.index - b.index)
    .map(({ entry }) => entry);

  return {
    open(entry) {
      entries = entries.filter((e) => e.id !== entry.id);
      const replaced = entry.kind === "drawer"
        ? entries.filter((e) => e.kind === "drawer" && (e.side ?? "right") === (entry.side ?? "right"))
        : [];
      entries = [...entries.filter((e) => !replaced.includes(e)), entry];
      notify();
      return replaced;
    },
    close(id) {
      const before = entries.length;
      entries = entries.filter((e) => e.id !== id);
      if (entries.length !== before) notify();
    },
    layers: ordered,
    top() {
      const list = ordered();
      return list[list.length - 1];
    },
    escape() {
      const list = ordered();
      for (let i = list.length - 1; i >= 0; i--) {
        const entry = list[i];
        if (!entry) continue;
        if (entry.closeOnEscape === false) return false; // the top layer keeps focus; nothing below closes
        entry.requestClose();
        return true;
      }
      return false;
    },
    zIndex(id) {
      const list = ordered();
      const entry = list.find((e) => e.id === id);
      if (!entry) return undefined;
      const position = list.filter((e) => e.kind === entry.kind).indexOf(entry);
      return BAND_BASE[entry.kind] + position * 2;
    },
    inert(id) {
      const list = ordered();
      const index = list.findIndex((e) => e.id === id);
      if (index < 0) return false;
      return list.slice(index + 1).some((e) => e.kind === "modal");
    },
    hasModal() {
      return entries.some((e) => e.kind === "modal");
    },
    subscribe(listener) {
      listeners.add(listener);
      return () => { listeners.delete(listener); };
    },
  };
}
