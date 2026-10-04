import { shortcutModifier } from "../../shared/shortcutModifier.js";
import { Suspense, lazy, useCallback, useEffect, useRef, useState } from "react";
import { t, translateMarketType } from "../../i18n/index.js";
import { useLocale } from "../../i18n/useLocale.js";
import { markPerf } from "../../runtime/performance/perfMarks";
import type { UseSymbolSearchRuntimeOptions, SymbolSelection } from "./useSymbolSearchRuntime.js";
import { quickSearchCharacter, searchKeyboardBlocked } from "./symbolSearchShortcut.js";

export type SymbolSearchProps = Omit<
  UseSymbolSearchRuntimeOptions,
  "open" | "onClose" | "initialSearch"
>;

function loadSymbolSearchModal() {
  return import("./SymbolSearchModal");
}

const SymbolSearchModal = lazy(loadSymbolSearchModal);

export default function SymbolSearch({
  currentSymbol,
  currentMarketType,
  currentExchange = "binance",
  onSelect,
  exchangeCatalog,
  watchlists,
  onAddToWatchlist,
}: SymbolSearchProps) {
  useLocale();
  const [open, setOpen] = useState(false);
  const [initialSearch, setInitialSearch] = useState("");
  const opening = useRef(false);

  const handleOpen = useCallback(() => {
    markPerf("lazy.symbolSearch.open.start", { trigger: "button" });
    opening.current = true;
    setInitialSearch("");
    setOpen(true);
  }, []);

  const handleClose = useCallback(() => {
    opening.current = false;
    setOpen(false);
  }, []);

  const handleSelect = useCallback((symbol: SymbolSelection) => {
    onSelect(symbol);
    opening.current = false;
    setOpen(false);
  }, [onSelect]);

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.isComposing || event.keyCode === 229) return;
      if ((event.ctrlKey || event.metaKey) && !event.altKey && event.key.toLowerCase() === "k") {
        event.preventDefault();
        if (event.repeat) return;
        opening.current = !opening.current;
        if (opening.current) markPerf("lazy.symbolSearch.open.start", { trigger: "keyboard" });
        setInitialSearch("");
        setOpen(opening.current);
        return;
      }
      // Buffer rapid input while the lazy modal chunk is loading. Once mounted,
      // its focused input receives normal text editing, including key repeats.
      if (opening.current) {
        if (!document.querySelector(".sym-modal-search-input")) {
          if (event.key === "Escape") { event.preventDefault(); opening.current = false; setOpen(false); return; }
          if (event.key === "Backspace" && !event.ctrlKey && !event.metaKey && !event.altKey) {
            event.preventDefault(); setInitialSearch((value) => value.slice(0, -1)); return;
          }
          const character = quickSearchCharacter(event, false);
          if (character !== null) { event.preventDefault(); setInitialSearch((value) => (value + character).slice(0, 120)); }
        }
        return;
      }
      const blocked = searchKeyboardBlocked(document, event);
      const character = quickSearchCharacter(event, blocked);
      if (character !== null || (event.key === "/" && !blocked && !event.ctrlKey && !event.metaKey && !event.altKey && !event.repeat)) {
        event.preventDefault();
        markPerf("lazy.symbolSearch.open.start", { trigger: "keyboard" });
        opening.current = true;
        setInitialSearch(character || "");
        setOpen(true);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  return (
    <>
      <button
        className="symbol-selector ui-control"
        id="symbol-selector"
        onPointerEnter={loadSymbolSearchModal}
        onMouseOver={loadSymbolSearchModal}
        onMouseEnter={loadSymbolSearchModal}
        onFocus={loadSymbolSearchModal}
        onClick={handleOpen}
        title={t("search.title", { modifier: shortcutModifier() })}
      >
        <span className="symbol-name" title={currentSymbol}>{currentSymbol}</span>
        {currentMarketType === "futures" && (
          <span className="symbol-market-badge futures">{translateMarketType("futures")}</span>
        )}
        <span className="symbol-exchange">
          {currentExchange.charAt(0).toUpperCase() + currentExchange.slice(1)}
        </span>
        <span className="symbol-shortcut-badge">
          <kbd>{shortcutModifier()}</kbd><kbd>K</kbd>
        </span>
      </button>

      {open && (
        <Suspense fallback={null}>
          <SymbolSearchModal
            open={open}
            initialSearch={initialSearch}
            onClose={handleClose}
            currentSymbol={currentSymbol}
            currentExchange={currentExchange}
            onSelect={handleSelect}
            {...(currentMarketType === undefined ? {} : { currentMarketType })}
            {...(exchangeCatalog === undefined ? {} : { exchangeCatalog })}
            {...(watchlists === undefined ? {} : { watchlists })}
            {...(onAddToWatchlist === undefined ? {} : { onAddToWatchlist })}
          />
        </Suspense>
      )}
    </>
  );
}
