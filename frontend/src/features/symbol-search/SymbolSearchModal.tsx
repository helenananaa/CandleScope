import { watchlistDisplayName } from "../watchlist/watchlistDisplayName.js";
import { Icon } from "../../components/icons/Icon.js";
import { shortcutModifier } from "../../shared/shortcutModifier.js";
import { t, tKey, translateMarketType } from "../../i18n/index.js";
import { useLocale } from "../../i18n/useLocale.js";
import { formatExchangeLabel } from "./symbolSearchFilter";
import { SourcePicker } from "./SourcePicker";
import { useSymbolSearchRuntime } from "./useSymbolSearchRuntime";
import type { UseSymbolSearchRuntimeOptions } from "./useSymbolSearchRuntime.js";
import type { SymbolSearchItem } from "./symbolSearchTypes.js";

export type SymbolSearchModalProps = UseSymbolSearchRuntimeOptions;

/** The venue line is shown only when it names something other than the source itself. */
function distinctVenue(
  symbol: SymbolSearchItem,
  exchangeCatalog: Parameters<typeof formatExchangeLabel>[1],
): boolean {
  if (!symbol.venue) return false;
  const venue = symbol.venue.toLowerCase();
  const source = symbol.providerId || symbol.exchange || "binance";
  const label = formatExchangeLabel(source, exchangeCatalog).toLowerCase().replace(/\s+/g, "");
  return venue !== source.toLowerCase() && venue !== label;
}

function marketTabLabel(key: string, fallback: string): string {
  if (key === "favorites") return t("search.tab.favorites");
  if (key === "spot" || key === "futures") return translateMarketType(key);
  return fallback;
}

export default function SymbolSearchModal(props: SymbolSearchModalProps) {
  const locale = useLocale();
  const runtime = useSymbolSearchRuntime(props);
  const { view, actions, status, refs } = runtime;
  const { inputRef, listRef, modalRef } = refs;
  const {
    search,
    marketType,
    exchangeFilter,
    quoteFilter,
    quoteOptions,
    favorites,
    favoriteSet,
    exchangeChips,
    assetClass, venue, scope, facets, discovery,
    filteredSymbols,
    highlightIndex,
    contextMenu,
    hasWatchlists,
    virtualRows,
  } = view;
  const {
    setSearch,
    setMarketType,
    setQuoteFilter,
    setHighlightIndex,
    selectExchange,
    toggleFavorite,
    selectSymbol,
    openContextMenu,
    addContextSymbolToWatchlist,
    getSymbolWatchlists,
    handleKeyDown,
    handleScroll,
    refreshSymbols, setAssetClass, setVenue, setScope, loadMore,
  } = actions;
  const {
    open,
    onClose,
    currentSymbol,
    currentMarketType,
    currentExchange = "binance",
    watchlists,
  } = props;

  if (!open) return null;

  return (
    <div className="sym-modal-overlay" onClick={onClose}>
      <div
        className="sym-modal"
        role="dialog"
        aria-modal="true"
        aria-label={t("search.title", { modifier: shortcutModifier() })}
        ref={modalRef}
        onClick={(event) => event.stopPropagation()}
        onKeyDown={handleKeyDown}
      >
        <div className="sym-modal-header">
          <div className="sym-modal-search-row">
            <svg className="sym-modal-search-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="11" cy="11" r="8" />
              <line x1="21" y1="21" x2="16.65" y2="16.65" />
            </svg>
            <input
              ref={inputRef}
              className="sym-modal-search-input"
              type="text"
              aria-label={t("search.title", { modifier: shortcutModifier() })}
              placeholder={t("search.placeholder", { modifier: shortcutModifier() })}
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              spellCheck={false}
              autoComplete="off"
            />
            {search && (
              <button className="sym-modal-search-clear" onClick={() => setSearch("")}>
                <Icon name="close" size={14} />
              </button>
            )}
            <button className="sym-modal-close-btn" onClick={onClose} title={t("search.close")}>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
                <line x1="18" y1="6" x2="6" y2="18" />
                <line x1="6" y1="6" x2="18" y2="18" />
              </svg>
            </button>
          </div>
        </div>

        <div className="sym-modal-filters">
          <div className="sym-modal-filter-row">
            <div className="sym-modal-market-tabs" aria-label={t("search.scope")}>
              {(["all", "recent", "favorites"] as const).map((key) => <button key={key}
                className={`sym-modal-market-tab ${scope === key ? "active" : ""}`}
                onClick={() => setScope(key)} aria-pressed={scope === key}>
                {key === "all" ? t("interval.tab.all") : key === "recent" ? t("search.recent") : t("search.tab.favorites")}
                {key === "favorites" && favorites.length > 0 && <span className="sym-modal-tab-badge">{favorites.length}</span>}
              </button>)}
            </div>
          </div>
          <div className="sym-modal-filter-row sym-modal-filter-row-chips">
            <label className="sym-modal-chip-group"><span className="sym-modal-chip-label">{t("search.assetClass")}</span>
              <select className="sym-modal-exchange-select" value={assetClass} onChange={(event) => setAssetClass(event.target.value)}>
                {["", "crypto", "stock", "etf", "forex", "commodity", "index"].map((key) => <option key={key} value={key}>
                  {key ? tKey(`search.asset.${key}`) : t("interval.tab.all")}
                </option>)}
              </select>
            </label>
            <SourcePicker sources={exchangeChips} selected={Array.from(exchangeFilter)[0] || ""} onSelect={selectExchange} />
            <label className="sym-modal-chip-group"><span className="sym-modal-chip-label">{t("search.exchange")}</span>
              <select className="sym-modal-exchange-select" value={venue} onChange={(event) => setVenue(event.target.value)}>
                <option value="">{t("interval.tab.all")}</option>
                {venue && !facets?.venues.some((item) => item.key === venue) && <option value={venue}>{venue}</option>}
                {facets?.venues.map((item) => <option key={item.key} value={item.key}>{item.key} ({item.count})</option>)}
              </select>
            </label>
            <label className="sym-modal-chip-group"><span className="sym-modal-chip-label">{t("search.type")}</span>
              <select className="sym-modal-exchange-select" value={marketType} onChange={(event) => setMarketType(event.target.value)}>
                <option value="">{t("interval.tab.all")}</option>
                {marketType && !facets?.markets.some((item) => item.key === marketType) && <option value={marketType}>{marketType}</option>}
                {facets?.markets.map((item) => <option key={item.key} value={item.key}>{marketTabLabel(item.key,
                  Object.values(props.exchangeCatalog || {}).flatMap((entry) => entry.markets || []).find((market) => market.market_type === item.key)?.label || translateMarketType(item.key))}</option>)}
              </select>
            </label>
            {<label className="sym-modal-chip-group">
              <span className="sym-modal-chip-label">{t("search.quote")}</span>
              <select id="sym-modal-quote-select" className="sym-modal-exchange-select" value={quoteFilter} onChange={(event) => setQuoteFilter(event.target.value)}>
                <option value="ALL">{t("interval.tab.all")}</option>
                {quoteFilter !== "ALL" && !quoteOptions.includes(quoteFilter) && <option value={quoteFilter}>{quoteFilter}</option>}
                {quoteOptions.map((quote) => <option key={quote} value={quote}>{quote}</option>)}
              </select>
            </label>}
          </div>
        </div>
        {status.error && <div className="sym-discovery-error" role="alert">{t("search.failed")} <button onClick={refreshSymbols}>{t("shell.retry")}</button></div>}

        <div className="sym-modal-table-header">
          <span className="sym-modal-col-fav" />
          <span className="sym-modal-col-pair">{t("search.pair")}</span>
          <span className="sym-modal-col-base">{t("workspace.groupName")}</span>
          <span className="sym-modal-col-quote">{t("search.quoteAsset")}</span>
          <span className="sym-modal-col-type">{t("search.type")}</span>
          <span className="sym-modal-col-exchange">{t("research.drawer.title")}</span>
        </div>

        <div
          className="sym-modal-list"
          aria-busy={status.refreshing}
          style={{ height: virtualRows.listHeight, opacity: status.stale ? 0.55 : 1, pointerEvents: status.stale ? "none" : undefined }}
          ref={listRef}
          onScroll={handleScroll}
        >
          {status.loading ? (
            <div className="sym-modal-empty">
              <div className="sym-modal-spinner" />
              <span>{t("search.loading")}</span>
            </div>
          ) : filteredSymbols.length === 0 ? (
            <div className="sym-modal-empty">
              <span className="sym-modal-empty-icon">
                <Icon name={scope === "favorites" ? "star" : "search"} size={28} />
              </span>
              <span>
                {scope === "favorites" && favorites.length === 0
                  ? t("search.noFavorites")
                  : !search && exchangeFilter.size > 0 && discovery?.sources.some((source) => source.status === "query_required")
                    ? t("search.sourceStatus.query_required")
                    : t("search.noResults")}
              </span>
            </div>
          ) : (
            <div style={{ height: virtualRows.totalHeight, position: "relative" }}>
              <div
                style={{
                  position: "absolute",
                  top: virtualRows.offsetY,
                  left: 0,
                  right: 0,
                }}
              >
                {virtualRows.visibleItems.map((symbol, index) => {
                  const realIndex = virtualRows.startIndex + index;
                  const isHighlighted = realIndex === highlightIndex;
                  const isCurrent = (
                    symbol.symbol === currentSymbol
                    && symbol.marketType === (currentMarketType || "spot")
                    && (symbol.exchange || "binance") === (currentExchange || "binance")
                  );
                  const isFavorite = favoriteSet.has(symbol._key);
                  const inWatchlists = getSymbolWatchlists(symbol._key);

                  return (
                    <div
                      key={symbol.seriesKey || symbol._key}
                      className={`sym-modal-row sym-discovery-row ${symbol.groupStart ? "sym-discovery-group-start" : ""} ${isHighlighted ? "highlighted" : ""} ${isCurrent ? "current" : ""}`}
                      style={{ height: virtualRows.rowHeight }}
                      onClick={() => selectSymbol(symbol)}
                      onMouseEnter={() => setHighlightIndex(realIndex)}
                      onContextMenu={(event) => openContextMenu(event, symbol.symbol, symbol._key)}
                    >

                      <button
                        className={`sym-modal-fav-btn ${isFavorite ? "active" : ""}`}
                        disabled={status.stale}
                        onClick={(event) => toggleFavorite(symbol._key, event)}
                        title={isFavorite ? t("search.unfavorite") : t("search.favorite")}
                      >
                        <Icon name="star" size={14} filled={isFavorite} />
                      </button>
                      <span className="sym-modal-col-pair sym-modal-row-pair" title={symbol.symbol}>
                        {symbol.baseAsset && symbol.quoteAsset ? `${symbol.baseAsset}/${symbol.quoteAsset}` : symbol.symbol}
                        {isCurrent && <span className="sym-modal-current-tag">{t("search.current")}</span>}
                        {hasWatchlists && inWatchlists.length > 0 && (
                          <span className="sym-modal-wl-indicators">
                            {inWatchlists.map((watchlist) => (
                              <span
                                key={watchlist.id}
                                className="sym-modal-wl-dot"
                                style={{ background: watchlist.color || "var(--accent-blue)" }}
                                title={t("search.inList", { name: watchlistDisplayName(watchlist) })}
                              />
                            ))}
                          </span>
                        )}
                      </span>
                      <span className="sym-modal-col-base sym-modal-row-base">
                        {typeof symbol.displayName === "string" && symbol.displayName ? symbol.displayName : symbol.baseAsset}
                        {symbol.groupStart && (symbol.groupSourceCount || 0) > 1 && <small className="sym-discovery-group-count">{t("search.sourceCount", { count: symbol.groupSourceCount || 0 })}</small>}
                      </span>
                      <span className="sym-modal-col-quote sym-modal-row-quote">{symbol.quoteAsset}</span>
                      <span className="sym-modal-col-type sym-modal-row-type">
                        <span className={`sym-modal-type-badge ${symbol.marketType}`}>
                          {marketTabLabel(symbol.marketType, props.exchangeCatalog?.[symbol.exchange]?.markets?.find((market) => market.market_type === symbol.marketType)?.label || translateMarketType(symbol.marketType))}
                        </span>
                      </span>
                      <span className="sym-modal-col-exchange sym-modal-row-exchange">
                        <span>{formatExchangeLabel(symbol.providerId || symbol.exchange || "binance", props.exchangeCatalog)}</span>
                        {distinctVenue(symbol, props.exchangeCatalog) && <small title={t("search.exchange")}>{symbol.venue}</small>}
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>

        <div className="sym-modal-footer">
          <div className="sym-modal-footer-left">
            <span
              className="sym-modal-result-count"
              title={`↑ ↓ · Enter · Esc ${t("search.shortcuts")}${hasWatchlists ? t("search.shortcutsWatchlist") : ""}`}
            >
              {t("search.pairCount", { count: (discovery?.total || filteredSymbols.length).toLocaleString(locale) })}
            </span>
            {discovery && <div className="sym-discovery-status">
              <details>
                <summary title={discovery.partial ? t("search.partial") : undefined}>
                  {discovery.partial && <span className="sym-discovery-partial-dot" aria-hidden="true" />}
                  {t("search.coverage", { ready: discovery.sources.filter((source) => ["ready", "stale", "limited"].includes(source.status)).length, total: discovery.sources.length })}
                </summary>
                <div className="sym-discovery-sources">
                  {discovery.partial && <p className="sym-discovery-partial">{t("search.partial")}</p>}
                  {discovery.sources.map((source) => <button key={source.id} onClick={() => selectExchange(source.id)}>
                    {formatExchangeLabel(source.id, props.exchangeCatalog)} · {tKey(`search.sourceStatus.${source.status}`)}
                  </button>)}
                </div>
              </details>
            </div>}
          </div>
          {discovery?.nextOffset != null && <button className="sym-modal-refresh-btn" disabled={status.refreshing} onClick={() => { void loadMore(); }}>{t("search.loadMore")}</button>}
          <button
            className="sym-modal-refresh-btn"
            onClick={refreshSymbols}
            disabled={status.refreshing}
            title={t("search.refreshTitle")}
          >
            <span className={`sym-modal-refresh-icon ${status.refreshing ? "spinning" : ""}`}><Icon name="refresh" size={14} /></span>
            {status.refreshing ? t("search.refreshing") : t("search.refresh")}
          </button>
        </div>
      </div>

      {contextMenu && hasWatchlists && (
        <div
          className="sym-ctx-menu"
          style={{ left: contextMenu.x, top: contextMenu.y }}
          onClick={(event) => event.stopPropagation()}
        >
          <div className="sym-ctx-header">
            <span className="sym-ctx-header-symbol">{contextMenu.symbol}</span>
            <span className="sym-ctx-header-label">{t("search.addToWatchlist")}</span>
          </div>
          <div className="sym-ctx-items">
            {(watchlists || []).map((watchlist) => {
              const alreadyIn = watchlist.symbols.includes(contextMenu._key);
              return (
                <button
                  key={watchlist.id}
                  className={`sym-ctx-item ${alreadyIn ? "already-in" : ""}`}
                  onClick={() => {
                    if (!alreadyIn) {
                      addContextSymbolToWatchlist(watchlist.id);
                    }
                  }}
                  disabled={alreadyIn}
                >
                  <span className="sym-ctx-dot" style={{ background: watchlist.color || "var(--accent-blue)" }} />
                  <span className="sym-ctx-name">{watchlistDisplayName(watchlist)}</span>
                  {alreadyIn ? (
                    <span className="sym-ctx-check"><Icon name="check" size={12} /></span>
                  ) : (
                    <span className="sym-ctx-plus">+</span>
                  )}
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
