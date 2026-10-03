import { t, type LocaleId, type MessageKey } from "../i18n/index.js";
import type { usePanePriceScaleMenu } from "./usePanePriceScaleMenu.js";

const PRICE_SCALE_MODES: readonly {
  value: number;
  labelKey: MessageKey;
  labelEn: string;
}[] = [
  { value: 0, labelKey: "scale.regular", labelEn: "Regular" },
  { value: 1, labelKey: "scale.log", labelEn: "Logarithmic" },
  { value: 2, labelKey: "scale.percent", labelEn: "Percentage" },
  { value: 3, labelKey: "scale.indexed", labelEn: "Indexed to 100" },
];

export default function PanePriceScaleMenu({
  menu, locale, onInvertScaleChange, onPriceScaleModeChange,
}: {
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
      <button
        type="button"
        className={`price-scale-menu-item${contextMenu.autoScale ? " active" : ""}`}
        onClick={() => {
          menu.applyOptions({ autoScale: !contextMenu.autoScale });
          menu.close();
        }}
      >
        <span className="price-scale-menu-check">{contextMenu.autoScale ? "✓" : ""}</span>
        <span>{t("scale.auto", {}, locale)}</span>
        {locale === "en" ? null : <span className="price-scale-menu-label-en">{t("scale.auto", {}, "en")}</span>}
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
          <span className="price-scale-menu-check">{contextMenu.invertScale ? "✓" : ""}</span>
          <span>{t("scale.invert", {}, locale)}</span>
          {locale === "en" ? null : <span className="price-scale-menu-label-en">{t("scale.invert", {}, "en")}</span>}
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
          <span className="price-scale-menu-check">{contextMenu.mode === mode.value ? "✓" : ""}</span>
          <span>{t(mode.labelKey, {}, locale)}</span>
          {locale === "en" ? null : <span className="price-scale-menu-label-en">{mode.labelEn}</span>}
        </button>
      ))}
    </div>
  );
}
