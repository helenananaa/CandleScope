import ToolFlyout from "./ToolFlyout.js";
import { openToolMenuFromKeyboard } from "./toolMenuKeys.js";
import type { ComponentPropsWithoutRef, ReactNode, RefObject } from "react";
import type { ToolbarVariant } from "./drawingToolbarDefinitions.js";

type VariantButtonEvents = Pick<
  ComponentPropsWithoutRef<"button">,
  "onClick" | "onContextMenu" | "onDoubleClick"
>;

export interface DrawingVariantToolButtonProps<TId extends string = string> extends VariantButtonEvents {
  active: boolean;
  anchorRef: RefObject<HTMLDivElement | null>;
  buttonClassName?: string;
  children?: ReactNode;
  currentId: TId;
  dataChartType?: string;
  dataDrawingTool?: string;
  disabled?: boolean;
  flyoutClassName?: string;
  flyoutKey: string;
  flyoutOpen: string | null;
  icon: ReactNode;
  isVariantDisabled?: ((variant: ToolbarVariant<TId>) => boolean) | null;
  onCloseFlyout(): void;
  onSelect(id: TId): void;
  title: string;
  variants: readonly ToolbarVariant<TId>[];
  wrapperClassName?: string;
}

const CornerTriangle = (
  <svg
    className="tool-variant-indicator"
    width="6"
    height="6"
    viewBox="0 0 6 6"
  >
    <polygon points="6,0 6,6 0,6" fill="currentColor" opacity="0.55" />
  </svg>
);

export default function DrawingVariantToolButton<TId extends string>({
  active,
  anchorRef,
  buttonClassName = "",
  children,
  currentId,
  dataChartType,
  dataDrawingTool,
  disabled = false,
  flyoutClassName = "",
  flyoutKey,
  flyoutOpen,
  icon,
  isVariantDisabled,
  onClick,
  onCloseFlyout,
  onContextMenu,
  onDoubleClick,
  onSelect,
  title,
  variants,
  wrapperClassName = "",
}: DrawingVariantToolButtonProps<TId>) {
  return (
    <div className={`drawing-tool-wrapper ${wrapperClassName}`.trim()} ref={anchorRef}>
      <button
        type="button"
        className={`drawing-tool-btn ${buttonClassName} ${active ? "active" : ""}`.trim()}
        data-chart-type={dataChartType}
        data-drawing-tool={dataDrawingTool}
        disabled={disabled}
        onClick={onClick}
        onDoubleClick={onDoubleClick}
        onContextMenu={onContextMenu}
        onKeyDown={onContextMenu ? openToolMenuFromKeyboard : undefined}
        // A click picks the tool and the variants open from right-click or the keyboard;
        // a button without that (the chart type) opens its menu on click.
        aria-haspopup={onContextMenu ? undefined : "menu"}
        aria-expanded={flyoutOpen === flyoutKey}
        title={title}
        aria-label={title}
      >
        {icon}
        {CornerTriangle}
      </button>
      {!disabled && flyoutOpen === flyoutKey && (
        <ToolFlyout
          variants={variants}
          currentId={currentId}
          onSelect={onSelect}
          onClose={onCloseFlyout}
          anchorRef={anchorRef}
          label={title}
          className={flyoutClassName}
          {...(isVariantDisabled === undefined ? {} : { isVariantDisabled })}
        />
      )}
      {!disabled && children}
    </div>
  );
}
