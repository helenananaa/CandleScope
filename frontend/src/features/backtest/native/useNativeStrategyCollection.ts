import { useCallback, useRef, useState } from "react";
import { t } from "../../../i18n/index.js";
import type { StrategySwitcherAction, StrategySwitcherItem } from "../chart-tester/StrategySwitcher.js";
import { copyNativeStrategy, normalizeNativeStrategies, strategyInstanceScope, type NativeStrategyCollection, type NativeStrategyInstance } from "./nativeStrategyCollection.js";

export function nativeStrategyName(item: NativeStrategyInstance): string {
  return item.name || t("strategyCollection.default");
}

/** The chart's strategy list. Owned above the panes so the dock header can switch and manage it. */
export function useNativeStrategyCollection(
  initial: NativeStrategyCollection | undefined,
  persist: ((value: NativeStrategyCollection) => void) | undefined,
  cellScope: string,
) {
  const collectionKey = `candlescope.native-strategies:${cellScope}`;
  const [collection, setCollection] = useState(() => {
    if (initial !== undefined) return normalizeNativeStrategies(initial);
    try { return normalizeNativeStrategies(JSON.parse(localStorage.getItem(collectionKey) ?? "null")); }
    catch { return normalizeNativeStrategies(null); }
  });
  const current = useRef(collection);
  const persistRef = useRef(persist);
  persistRef.current = persist;
  const [busyIds, setBusyIds] = useState<ReadonlySet<string>>(() => new Set());
  const [comparing, setComparing] = useState(false);
  const [renaming, setRenaming] = useState(false);
  const [storageError, setStorageError] = useState("");
  const update = useCallback((change: (value: NativeStrategyCollection) => NativeStrategyCollection) => {
    const next = change(current.current);
    current.current = next; setCollection(next);
    if (persistRef.current) persistRef.current(next);
    else {
      try { localStorage.setItem(collectionKey, JSON.stringify(next)); setStorageError(""); }
      catch { setStorageError(t("native.saveFailed")); }
    }
  }, [collectionKey]);
  const updateInstance = useCallback((id: string, change: Partial<NativeStrategyInstance>) => {
    update((value) => ({ ...value, items: value.items.map((item) => item.id === id ? { ...item, ...change, drafts: { ...item.drafts, ...change.drafts }, runs: { ...item.runs, ...change.runs }, runHistory: { ...item.runHistory, ...change.runHistory } } : item) }));
  }, [update]);
  const setInstanceBusy = useCallback((key: string, busy: boolean) => {
    setBusyIds((old) => { if (old.has(key) === busy) return old; const next = new Set(old); if (busy) next.add(key); else next.delete(key); return next; });
  }, []);
  const isBusy = (id: string) => [...busyIds].some((key) => key.startsWith(`${id}:`));
  const selected = collection.items.find((item) => item.id === collection.activeId);
  const select = (id: string) => { update((value) => ({ ...value, activeId: id })); setRenaming(false); setComparing(false); };
  const add = (copy: boolean) => {
    const id = crypto.randomUUID();
    if (copy && !selected) return;
    const drafts = { ...selected?.drafts };
    if (copy && selected) {
      try {
        for (const language of ["pine"]) for (const mode of ["NATIVE", "CANDLESCOPE"]) {
          const key = `${language}:${mode}`;
          const prefix = `candlescope.native-draft:${strategyInstanceScope(cellScope, selected.id)}:${language}`;
          const saved = drafts[key] ?? localStorage.getItem(`${prefix}:${mode}`) ?? (selected.id === "default" ? localStorage.getItem(prefix) : null);
          if (saved) drafts[key] = saved;
        }
      } catch { setStorageError(t("native.saveFailed")); return; }
    }
    const item = copy && selected ? copyNativeStrategy({ ...selected, drafts }, id, `${nativeStrategyName(selected)} · ${t("strategyCollection.copyName")}`)
      : { id, name: `${t("strategyCollection.default")} ${collection.items.length + 1}`, language: "pine" as const, drafts: {}, runs: {} };
    update((value) => ({ ...value, activeId: id, items: [...value.items, item] }));
    setRenaming(false); setComparing(false);
  };
  const remove = () => {
    if (!selected || isBusy(selected.id)) return;
    update((value) => normalizeNativeStrategies({ ...value, items: value.items.filter((item) => item.id !== selected.id) }));
    setRenaming(false);
  };
  const rename = (name: string | null) => {
    if (selected && name !== null) updateInstance(selected.id, { name: name.trim().slice(0, 80) });
    setRenaming(false);
  };
  return { collection, selected, update, updateInstance, setInstanceBusy, isBusy, select, add, remove, rename,
    comparing, setComparing, renaming, setRenaming, storageError };
}

export type NativeStrategyController = ReturnType<typeof useNativeStrategyCollection>;

export function nativeStrategySwitcherItems(strategies: NativeStrategyController): StrategySwitcherItem[] {
  return strategies.collection.items.map((item) => ({
    id: item.id,
    name: nativeStrategyName(item),
    meta: t("chartTester.language.pine"),
    running: strategies.isBusy(item.id),
  }));
}

export function nativeStrategySwitcherActions(strategies: NativeStrategyController): StrategySwitcherAction[] {
  const { selected } = strategies;
  const running = !!selected && strategies.isBusy(selected.id);
  return [
    { id: "add", label: t("strategyCollection.add"), onSelect: () => strategies.add(false) },
    { id: "copy", label: t("strategyCollection.copy"), disabled: !selected, onSelect: () => strategies.add(true) },
    { id: "rename", label: t("strategyCollection.rename"), disabled: !selected, onSelect: () => strategies.setRenaming(true) },
    { id: "remove", label: t("strategyCollection.remove"), disabled: !selected || running,
      ...(running ? { title: t("strategyCollection.runningHint") } : {}), onSelect: strategies.remove },
    { id: "compare", label: t("strategyCompare.title"), disabled: strategies.collection.items.length === 0, onSelect: () => strategies.setComparing(true) },
  ];
}
