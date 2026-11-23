import type { ComponentPropsWithoutRef, ReactNode, RefObject } from "react";
import { IconButton } from "../ui/index.js";
import { openToolMenuFromKeyboard } from "./toolMenuKeys.js";

type DrawingButtonEvents = Pick<
  ComponentPropsWithoutRef<"button">,
  "onClick" | "onContextMenu" | "onDoubleClick"
>;

export interface DrawingToolButtonProps extends DrawingButtonEvents {
  active: boolean;
  anchorRef?: RefObject<HTMLDivElement | null>;
  children?: ReactNode;
  dataDrawingTool?: string;
  disabled?: boolean;
  icon: ReactNode;
  showVariantIndicator?: boolean;
  title: string;
}

/** Marks a tool that has variants (right-click, → or the menu key opens them). */
const CornerTriangle = (
  <svg width="6" height="6" viewBox="0 0 6 6">
    <polygon points="6,0 6,6 0,6" fill="currentColor" opacity="0.55" />
  </svg>
);

export default function DrawingToolButton({
  active,
  anchorRef,
  children,
  dataDrawingTool,
  disabled = false,
  icon,
  onClick,
  onContextMenu,
  onDoubleClick,
  showVariantIndicator = false,
  title,
}: DrawingToolButtonProps) {
  return (
    <div className="drawing-tool-wrapper" ref={anchorRef}>
      <IconButton
        className="drawing-tool-btn"
        label={title}
        icon={icon}
        pressed={active}
        indicator={showVariantIndicator ? CornerTriangle : undefined}
        data-drawing-tool={dataDrawingTool}
        disabled={disabled}
        onClick={onClick}
        onDoubleClick={onDoubleClick}
        onContextMenu={onContextMenu}
        onKeyDown={onContextMenu ? openToolMenuFromKeyboard : undefined}
      />
      {!disabled && children}
    </div>
  );
}
