import { OverlayLayer } from "../../components/ui/Overlays.js";
import { Button, IconButton } from "../../components/ui/Button.js";
import { SegmentedControl } from "../../components/ui/Choice.js";
import { Badge, Disclosure, InlineAlert } from "../../components/ui/Display.js";
import { EmptyState } from "../../components/ui/EmptyState.js";
import { Field, Select } from "../../components/ui/Field.js";
import { watchlistDisplayName } from "../watchlist/watchlistDisplayName.js";
import { Icon } from "../../components/icons/Icon.js";
import { shortcutModifier } from "../../shared/shortcutModifier.js";
import { t, tKey, translateMarketType } from "../../i18n/index.js";
import { useLocale } from "../../i18n/useLocale.js";
import { formatExchangeLabel, formatSymbolLabel } from "./symbolSearchFilter";
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
    previewSymbol,
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

  const marketLabel = (key: string, exchange?: string) => marketTabLabel(key,
    (exchange ? props.exchangeCatalog?.[exchange]?.markets?.find((market) => market.market_type === key)?.label : undefined)
      || Object.values(props.exchangeCatalog || {}).flatMap((entry) => entry.markets || []).find((market) => market.market_type === key)?.label
      || translateMarketType(key));
  const scopeOptions = (["all", "recent", "favorites"] as const).map((key) => ({
    value: key,
    label: key === "all" ? t("interval.tab.all")
      : key === "recent" ? t("search.recent")
        : favorites.length > 0 ? `${t("search.tab.favorites")} ${favorites.length.toLocaleString(locale)}` : t("search.tab.favorites"),
  }));

  return (
    <OverlayLayer kind="modal" onClose={onClose} initialFocusRef={inputRef}>
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
        <div className="sym-modal-search">
          <span className="sym-modal-search-icon" aria-hidden="true"><Icon name="search" size={16} /></span>
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
          {search && <IconButton size="sm" label={t("search.clear")} icon={<Icon name="close" size={14} />} onClick={() => setSearch("")} />}
          <IconButton size="sm" className="sym-modal-close-btn" label={t("search.close")} icon={<Icon name="close" size={16} />} onClick={onClose} />
        </div>

        <div className="sym-modal-filters">
          <SegmentedControl size="sm" label={t("search.scope")} value={scope} options={scopeOptions} onChange={setScope} />
          <div className="sym-modal-filter-grid">
            <Field label={t("search.assetClass")}>
              <Select size="sm" value={assetClass} onChange={(event) => setAssetClass(event.target.value)}>
                {["", "crypto", "stock", "etf", "forex", "commodity", "index"].map((key) => <option key={key} value={key}>
                  {key ? tKey(`search.asset.${key}`) : t("interval.tab.all")}
                </option>)}
              </Select>
            </Field>
            <div className="ui-field">
              <span className="ui-field-label" aria-hidden="true">{t("search.source")}</span>
              <SourcePicker sources={exchangeChips} selected={Array.from(exchangeFilter)[0] || ""} onSelect={selectExchange} />
            </div>
            <Field label={t("search.exchange")}>
              <Select size="sm" value={venue} onChange={(event) => setVenue(event.target.value)}>
                <option value="">{t("interval.tab.all")}</option>
                {venue && !facets?.venues.some((item) => item.key === venue) && <option value={venue}>{venue}</option>}
                {facets?.venues.map((item) => <option key={item.key} value={item.key}>{item.key} ({item.count})</option>)}
              </Select>
            </Field>
            <Field label={t("search.type")}>
              <Select size="sm" value={marketType} onChange={(event) => setMarketType(event.target.value)}>
                <option value="">{t("interval.tab.all")}</option>
                {marketType && !facets?.markets.some((item) => item.key === marketType) && <option value={marketType}>{marketType}</option>}
                {facets?.markets.map((item) => <option key={item.key} value={item.key}>{marketLabel(item.key)}</option>)}
              </Select>
            </Field>
            <Field label={t("search.quote")}>
              <Select size="sm" value={quoteFilter} onChange={(event) => setQuoteFilter(event.target.value)}>
                <option value="ALL">{t("interval.tab.all")}</option>
                {quoteFilter !== "ALL" && !quoteOptions.includes(quoteFilter) && <option value={quoteFilter}>{quoteFilter}</option>}
                {quoteOptions.map((quote) => <option key={quote} value={quote}>{quote}</option>)}
              </Select>
            </Field>
          </div>
        </div>
        {status.error && (
          <InlineAlert tone="danger" className="sym-modal-alert" action={<Button size="sm" onClick={refreshSymbols}>{t("shell.retry")}</Button>}>
            {t("search.failed")}
          </InlineAlert>
        )}

        <div className="sym-modal-table-header" aria-hidden="true">
          <span className="sym-modal-col-fav" />
          <span className="sym-modal-col-pair">{t("search.pair")}</span>
          <span className="sym-modal-col-base">{t("search.name")}</span>
          <span className="sym-modal-col-quote">{t("search.quoteAsset")}</span>
          <span className="sym-modal-col-type">{t("search.type")}</span>
          <span className="sym-modal-col-exchange">{t("search.source")}</span>
        </div>

        <div
          className="sym-modal-list"
          aria-busy={status.refreshing}
          data-stale={status.stale ? "true" : undefined}
          ref={listRef}
          onScroll={handleScroll}
        >
          {status.loading ? (
            <EmptyState compact icon={<span className="sym-modal-spinner" />} title={t("search.loading")} />
          ) : filteredSymbols.length === 0 ? (
            <EmptyState compact icon={<Icon name={scope === "favorites" ? "star" : "search"} size={24} />} title={
              scope === "favorites" && favorites.length === 0
                ? t("search.noFavorites")
                : !search && exchangeFilter.size > 0 && discovery?.sources.some((source) => source.status === "query_required")
                  ? t("search.sourceStatus.query_required")
                  : t("search.noResults")
            } />
          ) : (
            <div className="sym-modal-list-track" style={{ height: virtualRows.totalHeight }}>
              <div className="sym-modal-list-window" style={{ top: virtualRows.offsetY }}>
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
                      className={`sym-modal-row ${symbol.groupStart ? "sym-discovery-group-start" : ""} ${isHighlighted ? "highlighted" : ""} ${isCurrent ? "current" : ""}`}
                      style={{ height: virtualRows.rowHeight }}
                      onClick={() => selectSymbol(symbol)}
                      onMouseEnter={() => { setHighlightIndex(realIndex); previewSymbol(symbol); }}
                      onMouseLeave={props.onCancelPreview}
                      onContextMenu={(event) => openContextMenu(event, symbol.symbol, symbol._key)}
                    >
                      <span className="sym-modal-col-fav">
                        <IconButton
                          size="sm"
                          className="sym-modal-fav-btn"
                          pressed={isFavorite}
                          disabled={status.stale}
                          label={isFavorite ? t("search.unfavorite") : t("search.favorite")}
                          icon={<Icon name="star" size={14} filled={isFavorite} />}
                          onClick={(event) => toggleFavorite(symbol._key, event)}
                        />
                      </span>
                      <span className="sym-modal-col-pair sym-modal-row-pair" title={symbol.symbol}>
                        <span className="sym-modal-pair-label">{formatSymbolLabel(symbol)}</span>
                        {isCurrent && <Badge tone="accent">{t("search.current")}</Badge>}
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
                        <span className="sym-modal-cell-text">{typeof symbol.displayName === "string" && symbol.displayName ? symbol.displayName : symbol.baseAsset}</span>
                        {symbol.groupStart && (symbol.groupSourceCount || 0) > 1 && <small className="sym-modal-cell-note">{t("search.sourceCount", { count: symbol.groupSourceCount || 0 })}</small>}
                      </span>
                      <span className="sym-modal-col-quote">{symbol.quoteAsset}</span>
                      <span className="sym-modal-col-type">{marketLabel(symbol.marketType, symbol.exchange)}</span>
                      <span className="sym-modal-col-exchange sym-modal-row-exchange">
                        <span className="sym-modal-cell-text">{formatExchangeLabel(symbol.providerId || symbol.exchange || "binance", props.exchangeCatalog)}</span>
                        {distinctVenue(symbol, props.exchangeCatalog) && <small className="sym-modal-cell-note" title={t("search.exchange")}>{symbol.venue}</small>}
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>

        <div className="sym-modal-footer">
          <span
            className="sym-modal-result-count"
            title={`↑ ↓ · Enter · Esc ${t("search.shortcuts")}${hasWatchlists ? t("search.shortcutsWatchlist") : ""}`}
          >
            {t("search.pairCount", { count: (discovery?.total || filteredSymbols.length).toLocaleString(locale) })}
          </span>
          {discovery && (
            <Disclosure className="sym-coverage" summary={<>
              {discovery.partial && <span className="sym-coverage-partial" aria-hidden="true" />}
              {t("search.coverage", { ready: discovery.sources.filter((source) => ["ready", "stale", "limited"].includes(source.status)).length, total: discovery.sources.length })}
            </>}>
              {discovery.partial && <p className="sym-coverage-note">{t("search.partial")}</p>}
              <div className="sym-coverage-sources">
                {discovery.sources.map((source) => (
                  <button key={source.id} type="button" className="ui-menu-item" onClick={() => selectExchange(source.id)}>
                    <span className="ui-menu-label">{formatExchangeLabel(source.id, props.exchangeCatalog)}</span>
                    <span className="ui-menu-hint">{tKey(`search.sourceStatus.${source.status}`)}</span>
                  </button>
                ))}
              </div>
            </Disclosure>
          )}
          <span className="sym-modal-footer-actions">
            {discovery?.nextOffset != null && (
              <Button size="sm" variant="ghost" disabled={status.refreshing} onClick={() => { void loadMore(); }}>{t("search.loadMore")}</Button>
            )}
            <Button
              size="sm"
              variant="ghost"
              className="sym-modal-refresh-btn"
              data-refreshing={status.refreshing ? "true" : undefined}
              icon={<Icon name="refresh" size={14} />}
              onClick={refreshSymbols}
              disabled={status.refreshing}
              title={t("search.refreshTitle")}
            >
              {status.refreshing ? t("search.refreshing") : t("search.refresh")}
            </Button>
          </span>
        </div>
      </div>

      {contextMenu && hasWatchlists && (
        <div
          className="ui-popover ui-menu sym-ctx-menu"
          role="menu"
          aria-label={`${t("search.addToWatchlist")} · ${contextMenu.symbol}`}
          style={{ left: contextMenu.x, top: contextMenu.y }}
          onClick={(event) => event.stopPropagation()}
        >
          <div className="sym-ctx-header">
            <strong>{contextMenu.symbol}</strong>
            <span>{t("search.addToWatchlist")}</span>
          </div>
          <div className="ui-menu-list">
            {(watchlists || []).map((watchlist) => {
              const alreadyIn = watchlist.symbols.includes(contextMenu._key);
              return (
                <button
                  key={watchlist.id}
                  type="button"
                  role="menuitem"
                  className="ui-menu-item"
                  onClick={() => {
                    if (!alreadyIn) {
                      addContextSymbolToWatchlist(watchlist.id);
                    }
                  }}
                  disabled={alreadyIn}
                >
                  <span className="ui-menu-icon" aria-hidden="true">
                    <span className="sym-modal-wl-dot" style={{ background: watchlist.color || "var(--accent-blue)" }} />
                  </span>
                  <span className="ui-menu-label">{watchlistDisplayName(watchlist)}</span>
                  <span className="ui-menu-hint" aria-hidden="true"><Icon name={alreadyIn ? "check" : "plus"} size={12} /></span>
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
    </OverlayLayer>
  );
}
