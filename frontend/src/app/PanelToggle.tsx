import type { ReactNode } from "react";

import { IconButton } from "../components/ui/index.js";

/**
 * A header button that opens or closes a side panel (indicators, alerts): a kit icon button
 * that reports its state with aria-expanded and can carry a count badge.
 */
export function PanelToggle({ label, title, icon, open, onToggle, badge, className, disabled = false, controls }: {
  label: string;
  /** Tooltip when it should say more than the label (for example why it is disabled). */
  title?: string;
  icon: ReactNode;
  open: boolean;
  onToggle(): void;
  badge?: ReactNode;
  className: string;
  disabled?: boolean;
  controls?: string;
}) {
  return (
    <IconButton
      className={`panel-toggle ${className}`}
      label={label}
      {...(title ? { title } : {})}
      {...(controls ? { "aria-controls": controls } : {})}
      aria-expanded={open}
      disabled={disabled}
      onClick={onToggle}
      icon={<>{icon}{badge !== undefined && badge !== null && badge !== 0 ? <span className="indicator-badge">{badge}</span> : null}</>}
    />
  );
}
