import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "../../services/api.js";
import { fetchSymbolDiscovery, type DiscoveryQuery, type DiscoveryResult } from "./symbolDiscoveryApi.js";

export function useSymbolDiscovery(query: DiscoveryQuery, open: boolean) {
  const key = JSON.stringify(query);
  const [state, setState] = useState<{ key: string; result: DiscoveryResult | null; loading: boolean; error: string }>({
    key: "", result: null, loading: false, error: "",
  });
  const controller = useRef<AbortController | null>(null);
  const [epoch, setEpoch] = useState(0);
  const active = useRef("");
  const cache = useRef(new Map<string, { at: number; result: DiscoveryResult }>());
  const result = state.result;
  const stale = state.key !== key;

  useEffect(() => {
    active.current = key;
    if (!open) return;
    const abort = new AbortController();
    controller.current?.abort();
    controller.current = abort;
    const timer = setTimeout(() => {
      const cached = cache.current.get(key);
      setState((previous) => cached && Date.now() - cached.at < 60_000
        ? { key, result: cached.result, loading: true, error: "" }
        : { ...previous, loading: true, error: "" });
      void fetchSymbolDiscovery(JSON.parse(key) as DiscoveryQuery, abort.signal).then((value) => {
        if (!abort.signal.aborted) {
          cache.current.delete(key);
          cache.current.set(key, { at: Date.now(), result: value });
          while (cache.current.size > 20) cache.current.delete(cache.current.keys().next().value!);
          setState({ key, result: value, loading: false, error: "" });
        }
      }).catch((error: unknown) => {
        if (!abort.signal.aborted) setState((previous) => ({ key,
          result: previous.key === key ? previous.result : null, loading: false,
          error: error instanceof Error ? error.message : String(error) }));
      });
    }, query.search ? 250 : 0);
    return () => { clearTimeout(timer); abort.abort(); controller.current?.abort(); };
  }, [key, open, epoch, query.search]);

  useEffect(() => {
    if (!open || stale || state.loading || !result || result.symbols.length > 100
      || !result.sources.some((source) => source.status === "not_loaded")) return;
    const timer = setTimeout(() => setEpoch((value) => value + 1), 5000);
    return () => clearTimeout(timer);
  }, [open, stale, state.loading, result]);

  const fetchMore = useCallback(async (loadSources: string[] = []) => {
    if (!result || stale || state.loading || active.current !== key) return;
    const offset = loadSources.length ? 0 : result.nextOffset;
    if (offset === null) return;
    controller.current?.abort();
    const abort = new AbortController();
    controller.current = abort;
    setState((previous) => ({ ...previous, loading: true, error: "" }));
    try {
      const next = await fetchSymbolDiscovery(JSON.parse(key) as DiscoveryQuery, abort.signal, offset,
        offset ? result.revision : "", loadSources);
      if (abort.signal.aborted || active.current !== key) return;
      setState({ key, result: { ...next, symbols: offset ? [...result.symbols, ...next.symbols] : next.symbols }, loading: false, error: "" });
    } catch (error) {
      if (abort.signal.aborted || active.current !== key) return;
      if (error instanceof ApiError && error.status === 409) { setEpoch((value) => value + 1); return; }
      setState((previous) => ({ ...previous, loading: false, error: error instanceof Error ? error.message : String(error) }));
    }
  }, [key, result, stale, state.loading]);
  return {
    result, stale, loading: open && (stale || state.loading), error: state.key === key ? state.error : "",
    loadMore: () => fetchMore(),
    loadSources: () => fetchMore(result?.sources.filter((source) => source.status === "not_loaded").slice(0, 3).map((source) => source.id) || []),
    refresh: () => setEpoch((value) => value + 1),
  };
}
