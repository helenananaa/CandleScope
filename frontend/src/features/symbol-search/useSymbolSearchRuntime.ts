import { listenForSearchContextMenuDismiss } from "./searchContextMenuDismiss.js";
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { listenForSearchEscape } from "./searchEscape.js";
import { markPerf } from "../../runtime/performance/perfMarks";
import { useSymbolDiscovery } from "./useSymbolDiscovery";
import { loadRecentSymbols, rememberRecentSymbol } from "./sourcePreferences";
import { useSymbolFavoritesStore } from "./symbolFavoritesStore";
import {
  ROW_HEIGHT,
  VISIBLE_ROWS,
  buildExchangeChips,
  getSymbolWatchlists,
} from "./symbolSearchFilter";
import type {
  KeyboardEvent as ReactKeyboardEvent,
  MouseEvent as ReactMouseEvent,
  UIEvent as ReactUIEvent,
} from "react";
import type { WatchlistGroup } from "../watchlist/watchlistTypes.js";
import type {
  ExchangeCatalog,
  SymbolSearchItem,
} from "./symbolSearchTypes.js";
import {
  resolveKlineSeriesIdentity,
  type KlineSeriesIdentityInput,
} from "../market-data/klineSeriesIdentity.js";

const EMPTY_SYMBOLS: SymbolSearchItem[] = [];

export interface SymbolSelection extends KlineSeriesIdentityInput {
  symbol: string;
  marketType: string;
  exchange: string;
}

export interface SymbolContextMenu {
  x: number;
  y: number;
  symbol: string;
  _key: string;
}

export interface UseSymbolSearchRuntimeOptions {
  open: boolean;
  initialSearch?: string;
  onClose(): void;
  currentSymbol: string;
  currentMarketType?: string | null;
  currentExchange?: string;
  onSelect(selection: SymbolSelection): void;
  exchangeCatalog?: ExchangeCatalog | null;
  watchlists?: WatchlistGroup[] | null;
  onAddToWatchlist?: ((watchlistId: string, symbolKey: string) => void) | null;
}

export function useSymbolSearchRuntime({
  open,
  initialSearch = "",
  onClose,
  currentExchange = "binance",
  onSelect,
  exchangeCatalog,
  watchlists,
  onAddToWatchlist,
}: UseSymbolSearchRuntimeOptions) {
  const currentExchangeKey = currentExchange || "binance";

  const [search, setSearch] = useState(initialSearch);
  const [marketType, setMarketType] = useState("");
  const [exchangeFilter, setExchangeFilter] = useState<Set<string>>(() => new Set());
  const [quoteFilter, setQuoteFilter] = useState("ALL");
  const [highlightIndex, setHighlightIndex] = useState(0);
  const [scrollTop, setScrollTop] = useState(0);
  const [contextMenu, setContextMenu] = useState<SymbolContextMenu | null>(null);
  const [assetClass, setAssetClass] = useState("");
  const [venue, setVenue] = useState("");
  const [scope, setScope] = useState<"all" | "favorites" | "recent">("all");
  const [recent, setRecent] = useState(loadRecentSymbols);

  const inputRef = useRef<HTMLInputElement | null>(null);
  const listRef = useRef<HTMLDivElement | null>(null);
  const modalRef = useRef<HTMLDivElement | null>(null);

  const favoritesStore = useSymbolFavoritesStore();
  const catalog = useSymbolDiscovery({
    search, source: [...exchangeFilter][0] || "", asset_class: assetClass, market_type: marketType,
    venue, quote: quoteFilter === "ALL" ? "" : quoteFilter, preferred_source: currentExchangeKey,
    favorites: favoritesStore.favorites.slice(0, 500), recent, scope,
  }, open);
  const filteredSymbols = catalog.result?.symbols || EMPTY_SYMBOLS;
  const facets = catalog.result?.facets;
  const quoteOptions = facets?.quotes.map((item) => item.key) || [];

  useEffect(() => {
    if (open) markPerf("lazy.symbolSearch.ready");
  }, [open]);

  useLayoutEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);

  useEffect(() => {
    if (!open) return undefined;
    const resetTimer = setTimeout(() => {
      setMarketType("");
      setAssetClass("");
      setVenue("");
      setScope("all");
      setRecent(loadRecentSymbols());
      setExchangeFilter(new Set());
      setQuoteFilter("ALL");
      setHighlightIndex(0);
      setScrollTop(0);
      setContextMenu(null);
    }, 0);
    return () => {
      clearTimeout(resetTimer);
    };
  }, [currentExchangeKey, open]);

  const exchangeChips = buildExchangeChips({
    allSymbols: filteredSymbols, currentExchange: currentExchangeKey,
    ...(exchangeCatalog === undefined ? {} : { exchangeCatalog }),
  });

  useEffect(() => {
    const timer = setTimeout(() => {
      setHighlightIndex(0);
      setScrollTop(0);
      if (listRef.current) listRef.current.scrollTop = 0;
    }, 0);
    return () => clearTimeout(timer);
  }, [exchangeFilter, marketType, quoteFilter, search, assetClass, venue, scope]);

  useEffect(() => {
    if (!contextMenu) return undefined;
    return listenForSearchContextMenuDismiss(window, modalRef.current, () => setContextMenu(null));
  }, [contextMenu]);

  const selectSymbol = useCallback((entry: SymbolSearchItem) => {
    if (catalog.stale) return;
    const exchange = entry.exchange || "binance";
    rememberRecentSymbol(entry._key);
    onSelect({ symbol: entry.symbol, marketType: entry.marketType, exchange,
      ...resolveKlineSeriesIdentity(exchange, entry) });
    onClose();
  }, [catalog.stale, onClose, onSelect]);

  const toggleFavorite = useCallback((symbolKey: string, event?: { stopPropagation(): void } | null) => {
    event?.stopPropagation();
    favoritesStore.actions.toggleFavorite(symbolKey);
  }, [favoritesStore.actions]);

  const selectExchange = useCallback((exchange: string) => {
    setExchangeFilter(exchange ? new Set([exchange]) : new Set());
    setMarketType(""); setQuoteFilter("ALL"); setVenue("");
  }, []);

  const openContextMenu = useCallback((event: ReactMouseEvent, symbol: string, symbolKey: string) => {
    event.preventDefault();
    event.stopPropagation();
    if (!watchlists || watchlists.length === 0) return;
    setContextMenu({ x: event.clientX, y: event.clientY, symbol, _key: symbolKey });
  }, [watchlists]);

  const closeContextMenu = useCallback(() => {
    setContextMenu(null);
  }, []);

  const addContextSymbolToWatchlist = useCallback((watchlistId: string) => {
    if (contextMenu && onAddToWatchlist) {
      onAddToWatchlist(watchlistId, contextMenu._key);
    }
    setContextMenu(null);
  }, [contextMenu, onAddToWatchlist]);

  useEffect(() => {
    if (!open) return undefined;
    return listenForSearchEscape(document, () => {
      const picker = modalRef.current?.querySelector<HTMLDetailsElement>("details[open]");
      if (picker) { picker.open = false; picker.querySelector("summary")?.focus(); }
      else if (contextMenu) setContextMenu(null);
      else onClose();
    });
  }, [open, contextMenu, onClose]);

  const handleKeyDown = useCallback((event: ReactKeyboardEvent) => {
    if (event.nativeEvent.isComposing) return;
    const target = event.target as HTMLElement;
    if (event.key === "Tab") {
      const items = Array.from(modalRef.current?.querySelectorAll<HTMLElement>("input, select, button, summary, [tabindex]") || [])
        .filter((item) => item.tabIndex >= 0 && !item.matches(":disabled") && item.getClientRects().length > 0);
      const first = items[0], last = items[items.length - 1];
      if (event.shiftKey && target === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && target === last) { event.preventDefault(); first?.focus(); }
      return;
    }
    if (target !== inputRef.current && target.closest("input, select, button, summary, details")) return;
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setHighlightIndex((prev) => {
        const maxIndex = Math.max(0, filteredSymbols.length - 1);
        const next = Math.min(prev + 1, maxIndex);
        const topVisible = Math.floor(scrollTop / ROW_HEIGHT);
        const viewportRows = Math.max(1, Math.floor((listRef.current?.clientHeight || ROW_HEIGHT) / ROW_HEIGHT));
        const bottomVisible = topVisible + viewportRows - 1;
        if (next > bottomVisible && listRef.current) {
          listRef.current.scrollTop = (next - viewportRows + 1) * ROW_HEIGHT;
        }
        return next;
      });
      return;
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      setHighlightIndex((prev) => {
        const next = Math.max(prev - 1, 0);
        const topVisible = Math.floor(scrollTop / ROW_HEIGHT);
        if (next < topVisible && listRef.current) {
          listRef.current.scrollTop = next * ROW_HEIGHT;
        }
        return next;
      });
      return;
    }
    if (event.key === "Enter") {
      event.preventDefault();
      if (filteredSymbols[highlightIndex]) {
        selectSymbol(filteredSymbols[highlightIndex]);
      }
    }
  }, [filteredSymbols, highlightIndex, scrollTop, selectSymbol]);

  const handleScroll = useCallback((event: ReactUIEvent<HTMLDivElement>) => {
    const element = event.currentTarget;
    setScrollTop(element.scrollTop);
    if (element.scrollHeight - element.scrollTop - element.clientHeight < ROW_HEIGHT * 4 && !catalog.loading) {
      void catalog.loadMore();
    }
  }, [catalog]);

  const totalHeight = filteredSymbols.length * ROW_HEIGHT;
  const startIndex = Math.floor(scrollTop / ROW_HEIGHT);
  const endIndex = Math.min(startIndex + VISIBLE_ROWS + 3, filteredSymbols.length);
  const visibleItems = filteredSymbols.slice(startIndex, endIndex);
  const offsetY = startIndex * ROW_HEIGHT;
  const listHeight = VISIBLE_ROWS * ROW_HEIGHT;
  const hasWatchlists = Boolean(watchlists && watchlists.length > 0);

  return {
    view: {
      search, marketType, exchangeFilter, quoteFilter, quoteOptions, assetClass, venue, scope, facets,
      favorites: favoritesStore.favorites, favoriteSet: favoritesStore.favoriteSet,
      exchangeChips, filteredSymbols, highlightIndex, contextMenu, hasWatchlists,
      discovery: catalog.result,
      virtualRows: { rowHeight: ROW_HEIGHT, listHeight, totalHeight, startIndex, visibleItems, offsetY },
    },
    actions: {
      setSearch, setMarketType, setQuoteFilter, setHighlightIndex, selectExchange,
      setAssetClass: (value: string) => { setAssetClass(value); setMarketType(""); setVenue(""); setQuoteFilter("ALL"); },
      setVenue, setScope, toggleFavorite, selectSymbol, openContextMenu, closeContextMenu,
      addContextSymbolToWatchlist, getSymbolWatchlists: (key: string) => getSymbolWatchlists(watchlists, key),
      handleKeyDown, handleScroll, refreshSymbols: catalog.refresh, loadMore: catalog.loadMore, loadSources: catalog.loadSources,
    },
    status: { loading: catalog.loading && !catalog.result, refreshing: catalog.loading, stale: catalog.stale, error: catalog.error },
    refs: { inputRef, listRef, modalRef },
  };
}
export type SymbolSearchRuntime = ReturnType<typeof useSymbolSearchRuntime>;
