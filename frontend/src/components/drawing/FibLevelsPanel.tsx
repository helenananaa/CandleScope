import { useEffect, useRef, useState } from "react";
import { DEFAULT_FIB_LEVELS } from "../../features/drawings/primitives/FibonacciDrawingPrimitive.js";
import type { KeyboardEvent as ReactKeyboardEvent, RefObject } from "react";
import type { FibonacciLevel } from "../../features/drawings/drawingTypes.js";
import { t } from "../../i18n/index.js";
import { useLocale } from "../../i18n/useLocale.js";
import { IconButton, SegmentedControl, useAnchoredPopup } from "../ui/index.js";
import { Icon } from "../icons/Icon.js";

export interface FibLevelsPanelProps {
  levels?: FibonacciLevel[] | null;
  onLevelsChange(levels: FibonacciLevel[]): void;
  inverted: boolean;
  onInvertedChange(inverted: boolean): void;
  onClose(): void;
  anchorRef: RefObject<HTMLDivElement | null>;
}

const FIB_RANDOM_COLORS = [
  "#e91e63",
  "#9c27b0",
  "#673ab7",
  "#3f51b5",
  "#2196f3",
  "#00bcd4",
  "#4caf50",
  "#8bc34a",
  "#cddc39",
  "#ffc107",
  "#ff9800",
  "#ff5722",
  "#795548",
  "#607d8b",
];

export default function FibLevelsPanel({
  levels = DEFAULT_FIB_LEVELS,
  onLevelsChange,
  inverted,
  onInvertedChange,
  onClose,
  anchorRef,
}: FibLevelsPanelProps) {
  useLocale();
  const panelRef = useRef<HTMLDivElement | null>(null);
  // Escape closes it and focus goes back to the tool's button.
  useAnchoredPopup({ open: true, onClose, popupRef: panelRef });
  const [newLevelInput, setNewLevelInput] = useState("");
  const panelLevels = Array.isArray(levels) ? levels : DEFAULT_FIB_LEVELS;

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

  const toggleLevel = (index: number): void => {
    onLevelsChange(panelLevels.map((level, itemIndex) => (
      itemIndex === index ? { ...level, enabled: !level.enabled } : level
    )));
  };

  const changeLevelColor = (index: number, color: string): void => {
    onLevelsChange(panelLevels.map((level, itemIndex) => (
      itemIndex === index ? { ...level, color } : level
    )));
  };

  const removeLevel = (index: number): void => {
    onLevelsChange(panelLevels.filter((_, itemIndex) => itemIndex !== index));
  };

  const addCustomLevel = (): void => {
    const value = parseFloat(newLevelInput);
    if (!Number.isFinite(value)) return;
    if (panelLevels.some((level) => Math.abs(level.level - value) < 0.0001)) return;

    const color = FIB_RANDOM_COLORS.at(panelLevels.length % FIB_RANDOM_COLORS.length) ?? "#e91e63";
    const next = [...panelLevels, { level: value, color, enabled: true }]
      .sort((a, b) => a.level - b.level);
    onLevelsChange(next);
    setNewLevelInput("");
  };

  const handleKeyDown = (event: ReactKeyboardEvent<HTMLInputElement>): void => {
    if (event.key === "Enter") addCustomLevel();
    event.stopPropagation();
  };

  const isDefault = (level: FibonacciLevel): boolean => (
    DEFAULT_FIB_LEVELS.some((defaultLevel) => (
      Math.abs(defaultLevel.level - level.level) < 0.0001
    ))
  );

  return (
    <div className="fib-levels-panel" ref={panelRef} role="dialog" aria-label={t("drawing.settings.fibonacciLevels")}>
      <div className="fib-levels-header">
        <span>{t("drawing.settings.fibonacciLevels")}</span>
        <IconButton size="sm" label={t("common.close")} icon={<Icon name="close" size={14} />} data-overlay-close onClick={onClose} />
      </div>

      <div className="fib-invert-row">
        <span className="fib-invert-label" aria-hidden="true">{t("drawing.settings.firstClickDefines")}</span>
        <SegmentedControl
          size="sm"
          label={t("drawing.settings.firstClickDefines")}
          value={inverted ? "1" : "0"}
          options={[{ value: "0", label: "0" }, { value: "1", label: "1" }]}
          onChange={(value) => onInvertedChange(value === "1")}
        />
      </div>

      <div className="fib-levels-divider" />

      <div className="fib-levels-list">
        {panelLevels.map((level, index) => (
          <div key={index} className="fib-level-row">
            <input
              type="checkbox"
              checked={level.enabled}
              onChange={() => toggleLevel(index)}
              className="fib-level-check"
            />
            <input
              type="color"
              value={level.color}
              onChange={(event) => changeLevelColor(index, event.target.value)}
              className="fib-level-color"
            />
            <span className={`fib-level-value ${!level.enabled ? "disabled" : ""}`}>
              {level.level}
            </span>
            {!isDefault(level) && (
              <IconButton
                size="sm"
                variant="danger"
                className="fib-level-remove"
                label={t("drawing.settings.removeLevel")}
                icon={<Icon name="close" size={12} />}
                onClick={() => removeLevel(index)}
              />
            )}
          </div>
        ))}
      </div>

      <div className="fib-add-level-row">
        <input
          type="text"
          className="fib-add-level-input"
          placeholder={t("drawing.settings.addLevelPlaceholder")}
          value={newLevelInput}
          onChange={(event) => setNewLevelInput(event.target.value)}
          onKeyDown={handleKeyDown}
        />
        <IconButton size="sm" variant="secondary" label={t("drawing.settings.addLevelPlaceholder")} icon={<Icon name="plus" size={14} />} onClick={addCustomLevel} />
      </div>
    </div>
  );
}
