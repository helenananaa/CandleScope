import type { WatchlistRuntime } from "../watchlist/useWatchlistRuntime.js";
import { createWatchlistId, WATCHLIST_COLORS, MIN_WATCHLIST_WIDTH, MAX_WATCHLIST_WIDTH } from "../watchlist/watchlistStore.js";
import { command, type ControlCommandGroup } from "./commandRegistry.js";
import { array, bool, choice, empty, number, object, optional, schema, text } from "./commandSchema.js";
import { parseSymbolKey, symbolKey } from "../../utils/symbolKey.js";
import { sortWatchlists } from "../watchlist/watchlistSort.js";
import { publishControlFile, readControlFile } from "./controlFiles.js";
export const canonicalWatchlistSymbol = schema<string>({ type: "string", maxLength: 128, description: "Canonical symbol key: spot:BTCUSDT or okx:spot:BTC-USDT; use the app symbol catalog." }, (value) => {
  const key = text(128).parse(value); const parsed = parseSymbolKey(key);
  if (!/^[a-z0-9_-]{1,64}$/.test(parsed.exchange) || !/^[a-z0-9_-]{1,32}$/.test(parsed.marketType) || !/^[A-Z0-9][A-Z0-9_./-]{0,95}$/.test(parsed.symbol) || symbolKey(parsed.symbol, parsed.marketType, parsed.exchange) !== key) throw new Error("SYMBOL_KEY_INVALID"); return key;
});

export function watchlistCommands(runtime: WatchlistRuntime): ControlCommandGroup {
  const { view, actions: a } = runtime;
  const id = text(96), symbol = canonicalWatchlistSymbol;
  const requireList = (listId: string) => { const found = view.watchlists.find((list) => list.id === listId); if (!found) throw new Error("WATCHLIST_UNAVAILABLE"); return found; };
  return { id: "watchlist", title: "Watchlists and subscription tiers", context: () => ({ lists: view.watchlists, layout: view.layout, tiers: view.subscriptionTiers }),
    snapshot: () => ({ watchlists: view.watchlists, layout: view.layout, tiers: view.subscriptionTiers, resources: view.subscriptionResourceSummaries }), commands: [
      command("create", "Create a persisted watchlist.", object({ name: text(128), color: optional(choice(WATCHLIST_COLORS)) }), ({ name, color }) => {
        const listId = createWatchlistId(); a.setWatchlists((lists) => [...lists, { id: listId, name, color: color ?? WATCHLIST_COLORS[0], symbols: [] }]); return { listId };
      }),
      command("update", "Rename or recolor an existing watchlist.", object({ listId: id, name: optional(text(128)), color: optional(text(64)) }), ({ listId, name, color }) => {
        requireList(listId); a.setWatchlists((lists) => lists.map((list) => list.id === listId ? { ...list, ...(name === undefined ? {} : { name }), ...(color === undefined ? {} : { color }) } : list));
      }),
      command("delete", "Delete a watchlist; retain at least one list.", object({ listId: id }), ({ listId }) => {
        requireList(listId); if (view.watchlists.length <= 1) throw new Error("LAST_WATCHLIST"); a.setWatchlists((lists) => lists.filter((list) => list.id !== listId));
      }),
      command("setSymbols", "Replace/reorder a list's symbols using the canonical symbol keys returned by inspect.", object({ listId: id, symbols: array(symbol, 1024) }), ({ listId, symbols }) => {
        requireList(listId); if (new Set(symbols).size !== symbols.length) throw new Error("DUPLICATE_SYMBOL"); a.setWatchlists((lists) => lists.map((list) => list.id === listId ? { ...list, symbols } : list));
      }),
      command("addSymbol", "Add a canonical symbol key to a watchlist.", object({ listId: id, symbolKey: symbol }), ({ listId, symbolKey }) => { requireList(listId); a.addToWatchlist(listId, symbolKey); }),
      command("removeSymbol", "Remove a symbol from a watchlist.", object({ listId: id, symbolKey: symbol }), ({ listId, symbolKey }) => {
        requireList(listId); a.setWatchlists((lists) => lists.map((list) => list.id === listId ? { ...list, symbols: list.symbols.filter((key) => key !== symbolKey) } : list));
      }),
      command("reorder", "Reorder all watchlists by their IDs.", object({ listIds: array(id, 256) }), ({ listIds }) => {
        if (listIds.length !== view.watchlists.length || new Set(listIds).size !== listIds.length) throw new Error("WATCHLIST_ORDER_INVALID");
        a.setWatchlists(listIds.map(requireList));
      }),
      command("layout", "Set watchlist width/collapse preferences.", object({ width: optional(number(MIN_WATCHLIST_WIDTH, MAX_WATCHLIST_WIDTH)), collapsed: optional(bool), collapsedLists: optional(array(id, 256)) }),
        ({ width, collapsed, collapsedLists }) => { if (width !== undefined) a.setWidth(width); if (collapsed !== undefined) a.setSidebarCollapsed(collapsed); if (collapsedLists) a.setCollapsedLists(collapsedLists); }),
      command("setTier", "Request a subscription tier using the UI coordinator. Inspect to check eventual server state.", object({ symbolKey: symbol, tier: choice(["none", "price", "full"]) }), ({ symbolKey, tier }) => a.handleTierChange(symbolKey, tier)),
      command("refresh", "Refresh subscriptions from the server.", empty, () => a.refreshSubscriptions()),
      command("prices", "Read a bounded current quote snapshot for a watchlist.", object({ listId: id, limit: number(1, 500, true) }), ({ listId, limit }) => requireList(listId).symbols.slice(0, limit).map((key) => ({ symbolKey: key, tick: view.priceStore.getSymbolSnapshot(key) ?? null })), { readOnly: true }),
      command("sort", "Sort lists using one quote snapshot and the UI's stable missing-quote/tier policy.", object({ column: choice(["symbol", "price", "change", "changePct"]), direction: choice(["asc", "desc"]) }), ({ column, direction }) => a.setWatchlists((lists) => sortWatchlists(lists, column, direction, view.priceStore.getSnapshot(), view.subscriptionTiers))),
      command("export", "Export watchlists and layout to a bounded JSON fileRef.", empty, () => publishControlFile(new Blob([JSON.stringify({ schema: "candlescope.watchlists/1", watchlists: view.watchlists, layout: view.layout })], { type: "application/json" }), "watchlists.json")),
      command("import", "Validate a staged JSON watchlist document and replace the lists with explicit confirmation.", object({ fileRef: text(96), confirmed: choice([true]) }), async ({ fileRef }) => {
        const input = object({ schema: choice(["candlescope.watchlists/1"]), watchlists: array(object({ id, name: text(128), color: text(64), symbols: array(symbol, 1024) }), 256), layout: optional(object({ width: optional(number(MIN_WATCHLIST_WIDTH, MAX_WATCHLIST_WIDTH)), sidebarCollapsed: optional(bool), collapsedLists: optional(array(id, 256)) })) }).parse(JSON.parse(await (await readControlFile(fileRef)).text()));
        if (!input.watchlists.length || new Set(input.watchlists.map((row) => row.id)).size !== input.watchlists.length || input.watchlists.some((row) => new Set(row.symbols).size !== row.symbols.length)) throw new Error("WATCHLIST_DOCUMENT_INVALID");
        a.setWatchlists(input.watchlists); if (input.layout?.width !== undefined) a.setWidth(input.layout.width); if (input.layout?.sidebarCollapsed !== undefined) a.setSidebarCollapsed(input.layout.sidebarCollapsed); if (input.layout?.collapsedLists) a.setCollapsedLists(input.layout.collapsedLists);
      }),
    ] };
}
