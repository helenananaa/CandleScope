import { t, type LocaleId, type MessageKey } from "../i18n/index.js";
import { formatPrice, formatPriceDiff } from "../features/market-data/marketDataView.js";
import { Icon } from "./icons/Icon.js";
import { Menu, type MenuItem } from "./ui/index.js";
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
  const items: MenuItem[] = [];
  if (onReturnToLatest) {
    items.push({
      id: "latest",
      label: t(returnToLatestPending ? "status.returningRealtime" : "status.returnToRealtime", {}, locale),
      disabled: returnToLatestDisabled,
      onSelect: onReturnToLatest,
    });
  }
  const price = contextMenu.price;
  if (price !== null && onAddAlertAtPrice) {
    items.push({
      id: "alert",
      label: t("alert.addAlert", {}, locale),
      icon: <Icon name="bell" size={12} />,
      hint: formatPrice(price),
      separatorBefore: true,
      // Same precision as the label, not the raw pointer coordinate.
      onSelect: () => onAddAlertAtPrice(Number(formatPriceDiff(price))),
    });
  }
  items.push({
    id: "auto",
    label: t("scale.auto", {}, locale),
    checked: contextMenu.autoScale,
    separatorBefore: true,
    onSelect: () => { menu.applyOptions({ autoScale: !contextMenu.autoScale }); },
  });
  if (contextMenu.paneId !== "main" || onInvertScaleChange) {
    items.push({
      id: "invert",
      label: t("scale.invert", {}, locale),
      checked: contextMenu.invertScale,
      onSelect: () => {
        const next = !contextMenu.invertScale;
        if (contextMenu.paneId === "main" && onInvertScaleChange) onInvertScaleChange(next);
        else menu.applyOptions({ invertScale: next });
      },
    });
  }
  PRICE_SCALE_MODES.forEach((mode, index) => items.push({
    id: `mode-${mode.value}`,
    label: t(mode.labelKey, {}, locale),
    checked: contextMenu.mode === mode.value,
    radio: true,
    separatorBefore: index === 0,
    onSelect: () => {
      if (contextMenu.paneId === "main" && onPriceScaleModeChange) onPriceScaleModeChange(mode.value);
      else menu.applyOptions({ mode: mode.value });
    },
  }));
  return <Menu open onClose={menu.close} anchorPoint={{ x: contextMenu.x, y: contextMenu.y }} label={t("scale.menu", {}, locale)} items={items} />;
}
