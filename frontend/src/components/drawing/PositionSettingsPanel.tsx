import { useEffect, useRef, useState } from "react";
import type { RefObject } from "react";
import { t } from "../../i18n/index.js";
import { useLocale } from "../../i18n/useLocale.js";
import { Button, IconButton, useAnchoredPopup } from "../ui/index.js";
import { Icon } from "../icons/Icon.js";

export interface PositionSettingsPanelProps {
  positionSize: number;
  onPositionSizeChange(size: number): void;
  onClose(): void;
  anchorRef: RefObject<HTMLDivElement | null>;
}

const POSITION_SIZE_PRESETS = [100, 500, 1000, 5000, 10000, 50000];

export default function PositionSettingsPanel({
  positionSize,
  onPositionSizeChange,
  onClose,
  anchorRef,
}: PositionSettingsPanelProps) {
  useLocale();
  const panelRef = useRef<HTMLDivElement | null>(null);
  // Escape closes it and focus goes back to the tool's button.
  useAnchoredPopup({ open: true, onClose, popupRef: panelRef });
  const [localSize, setLocalSize] = useState(String(positionSize || 1000));

  useEffect(() => {
    const handler = (event: MouseEvent) => {
      if (!(event.target instanceof Node)) return;
      if (
        panelRef.current
        && !panelRef.current.contains(event.target)
        && anchorRef.current
        && !anchorRef.current.contains(event.target)
      ) {
        onClose();
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [anchorRef, onClose]);

  const handleSizeChange = (value: string): void => {
    setLocalSize(value);
    const numberValue = parseFloat(value);
    if (Number.isFinite(numberValue) && numberValue > 0) {
      onPositionSizeChange(numberValue);
    }
  };

  return (
    <div className="position-settings-panel" ref={panelRef} role="dialog" aria-label={t("drawing.settings.position")}>
      <div className="fib-levels-header">
        <span>{t("drawing.settings.position")}</span>
        <IconButton size="sm" label={t("common.close")} icon={<Icon name="close" size={14} />} data-overlay-close onClick={onClose} />
      </div>
      <div className="fib-levels-divider" />
      <div className="position-size-section">
        <label className="position-size-label">{t("drawing.settings.positionSize")}</label>
        <input
          type="number"
          className="position-size-input"
          value={localSize}
          onChange={(event) => handleSizeChange(event.target.value)}
          onKeyDown={(event) => event.stopPropagation()}
          min="0"
          step="100"
        />
        <div className="position-size-presets">
          {POSITION_SIZE_PRESETS.map((preset) => (
            <Button
              key={preset}
              size="sm"
              aria-pressed={Number(localSize) === preset}
              onClick={() => handleSizeChange(String(preset))}
            >
              {preset >= 1000 ? `${preset / 1000}K` : preset}
            </Button>
          ))}
        </div>
      </div>
    </div>
  );
}
