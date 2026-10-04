import type { ReactNode } from "react";

export interface EmptyStateProps {
  title: ReactNode;
  description?: ReactNode;
  icon?: ReactNode;
  tone?: "neutral" | "accent" | "warning" | "danger";
  action?: ReactNode;
  className?: string;
  role?: "status" | "alert";
  compact?: boolean;
}

/** Panel empty / waiting / error state; styles live in src/styles/components.css (.ui-empty). */
export function EmptyState({ title, description, icon, tone = "neutral", action, className, role = "status", compact = false }: EmptyStateProps) {
  const classes = ["ui-empty", compact ? "ui-empty-compact" : null, className].filter(Boolean).join(" ");
  return (
    <div className={classes} data-tone={tone} role={role} title={typeof description === "string" ? description : undefined}>
      {icon ? <span className="ui-empty-icon" aria-hidden="true">{icon}</span> : null}
      <div className="ui-empty-title">{title}</div>
      {description ? <div className="ui-empty-description">{description}</div> : null}
      {action ? <div className="ui-empty-action">{action}</div> : null}
    </div>
  );
}
