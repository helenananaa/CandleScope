import { t, type LocaleId, type MessageKey } from "../i18n/index.js";
import { formatPrice, formatPriceDiff } from "../features/market-data/marketDataView.js";
import { Icon } from "./icons/Icon.js";
import type { usePanePriceScaleMenu } from "./usePanePriceScaleMenu.js";

const PRICE_SCALE_MODES: readonly {
  value: number;
  labelKey: MessageKey;
}[] = [
  { value: 0, labelKey: "scale.regular" },
  { value: 1, labelKey: "scale.log" },
  { value: 2, labelKey: "scale.percent" },
  { value: 3, labelKey: "scale.indexed" },
];

export default function PanePriceScaleMenu({
  menu, locale, onInvertScaleChange, onPriceScaleModeChange, onAddAlertAtPrice, onReturnToLatest,
  returnToLatestDisabled = false, returnToLatestPending = false,
}: {
  /** Shown while the latest bar is scrolled out of view or not loaded. */
  onReturnToLatest?: (() => void) | null | undefined;
  returnToLatestDisabled?: boolean;
  returnToLatestPending?: boolean;
  onAddAlertAtPrice?: ((price: number) => void) | null | undefined;
  menu: ReturnType<typeof usePanePriceScaleMenu>;
  locale: LocaleId;
  onInvertScaleChange?: ((value: boolean) => void) | null | undefined;
  onPriceScaleModeChange?: ((mode: number) => void) | null | undefined;
}) {
  const { contextMenu } = menu;
  if (!contextMenu) return null;
  return (
    <div
      className="price-scale-context-menu"
      style={{ left: contextMenu.x, top: contextMenu.y }}
      onMouseDown={(event) => event.stopPropagation()}
    >
      {onReturnToLatest && (
        <>
          <button
            type="button"
            className="price-scale-menu-item"
            disabled={returnToLatestDisabled}
            onClick={() => {
              onReturnToLatest();
              menu.close();
            }}
          >
            <span className="price-scale-menu-check" aria-hidden="true" />
            <span>{t(returnToLatestPending ? "status.returningRealtime" : "status.returnToRealtime", {}, locale)}</span>
          </button>
          <div className="price-scale-menu-divider" role="separator" />
        </>
      )}
      {contextMenu.price !== null && onAddAlertAtPrice && (
        <>
          <button
            type="button"
            className="price-scale-menu-item price-scale-menu-alert"
            onClick={() => {
              // Same precision as the label, not the raw pointer coordinate.
              onAddAlertAtPrice(Number(formatPriceDiff(contextMenu.price)));
              menu.close();
            }}
          >
            <span className="price-scale-menu-check" aria-hidden="true"><Icon name="bell" size={12} /></span>
            <span>{t("alert.addAlert", {}, locale)}</span>
            <span className="price-scale-menu-price">{formatPrice(contextMenu.price)}</span>
          </button>
          <div className="price-scale-menu-divider" role="separator" />
        </>
      )}
      <button
        type="button"
        className={`price-scale-menu-item${contextMenu.autoScale ? " active" : ""}`}
        onClick={() => {
          menu.applyOptions({ autoScale: !contextMenu.autoScale });
          menu.close();
        }}
      >
        <span className="price-scale-menu-check">{contextMenu.autoScale ? <Icon name="check" size={12} /> : null}</span>
        <span>{t("scale.auto", {}, locale)}</span>
      </button>
      {(contextMenu.paneId !== "main" || onInvertScaleChange) && (
        <button
          type="button"
          className={`price-scale-menu-item${contextMenu.invertScale ? " active" : ""}`}
          onClick={() => {
            const next = !contextMenu.invertScale;
            if (contextMenu.paneId === "main" && onInvertScaleChange) {
              onInvertScaleChange(next);
            } else {
              menu.applyOptions({ invertScale: next });
            }
            menu.close();
          }}
        >
          <span className="price-scale-menu-check">{contextMenu.invertScale ? <Icon name="check" size={12} /> : null}</span>
          <span>{t("scale.invert", {}, locale)}</span>
        </button>
      )}
      <div className="price-scale-menu-divider" />
      {PRICE_SCALE_MODES.map((mode) => (
        <button
          type="button"
          key={mode.value}
          className={`price-scale-menu-item${contextMenu.mode === mode.value ? " active" : ""}`}
          onClick={() => {
            if (contextMenu.paneId === "main" && onPriceScaleModeChange) {
              onPriceScaleModeChange(mode.value);
            } else {
              menu.applyOptions({ mode: mode.value });
            }
            menu.close();
          }}
        >
          <span className="price-scale-menu-check">{contextMenu.mode === mode.value ? <Icon name="check" size={12} /> : null}</span>
          <span>{t(mode.labelKey, {}, locale)}</span>
        </button>
      ))}
    </div>
  );
}
