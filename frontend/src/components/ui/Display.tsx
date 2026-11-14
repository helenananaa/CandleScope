import type { ReactNode } from "react";

export type Tone = "neutral" | "accent" | "success" | "warning" | "danger";

export interface BadgeProps {
  tone?: Tone;
  children: ReactNode;
  className?: string;
  title?: string;
}

/** Short status or count label. */
export function Badge({ tone = "neutral", children, className, title }: BadgeProps) {
  return <span className={["ui-badge", className].filter(Boolean).join(" ")} data-tone={tone} title={title}>{children}</span>;
}

export interface SectionProps {
  title: ReactNode;
  description?: ReactNode;
  /** Buttons or links shown at the end of the heading row. */
  actions?: ReactNode;
  /** Heading level inside the surrounding page. */
  level?: 2 | 3 | 4;
  className?: string;
  children?: ReactNode;
}

/** Titled group of related settings or content. */
export function Section({ title, description, actions, level = 3, className, children }: SectionProps) {
  const Heading = `h${level}` as const;
  return (
    <section className={["ui-section", className].filter(Boolean).join(" ")}>
      <header className="ui-section-head">
        <div className="ui-section-heading">
          <Heading className="ui-section-title">{title}</Heading>
          {description ? <p className="ui-section-description">{description}</p> : null}
        </div>
        {actions ? <div className="ui-section-actions">{actions}</div> : null}
      </header>
      {children != null ? <div className="ui-section-body">{children}</div> : null}
    </section>
  );
}

export interface StatProps {
  label: ReactNode;
  value: ReactNode;
  /** Secondary line, such as a change or a unit. */
  hint?: ReactNode;
  tone?: Tone;
  className?: string;
}

/** One labelled figure. Values use tabular numbers. */
export function Stat({ label, value, hint, tone = "neutral", className }: StatProps) {
  return (
    <div className={["ui-stat", className].filter(Boolean).join(" ")} data-tone={tone}>
      <span className="ui-stat-label">{label}</span>
      <strong className="ui-stat-value">{value}</strong>
      {hint ? <span className="ui-stat-hint">{hint}</span> : null}
    </div>
  );
}

export interface DisclosureProps {
  summary: ReactNode;
  defaultOpen?: boolean;
  /** Controlled: the disclosure is open while this is true; pair it with onToggle. */
  open?: boolean;
  onToggle?: (open: boolean) => void;
  id?: string;
  className?: string;
  children: ReactNode;
}

/** Hides secondary detail (diagnostics, technical details) until asked for. */
export function Disclosure({ summary, defaultOpen = false, open, onToggle, id, className, children }: DisclosureProps) {
  return (
    <details id={id} className={["ui-disclosure", className].filter(Boolean).join(" ")} open={(open ?? defaultOpen) || undefined}
      onToggle={onToggle ? (event) => onToggle(event.currentTarget.open) : undefined}>
      <summary className="ui-disclosure-summary">
        <svg className="ui-disclosure-chevron" width="10" height="10" viewBox="0 0 10 10" aria-hidden="true">
          <path d="M3 2l3 3-3 3" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        {summary}
      </summary>
      <div className="ui-disclosure-body">{children}</div>
    </details>
  );
}

export interface InlineAlertProps {
  tone?: Exclude<Tone, "neutral" | "accent"> | "info";
  title?: ReactNode;
  children?: ReactNode;
  action?: ReactNode;
  className?: string;
}

/** Message inside a panel. Danger announces itself; other tones are polite. */
export function InlineAlert({ tone = "info", title, children, action, className }: InlineAlertProps) {
  return (
    <div className={["ui-alert", className].filter(Boolean).join(" ")} data-tone={tone} role={tone === "danger" ? "alert" : "status"}>
      <div className="ui-alert-text">
        {title ? <strong className="ui-alert-title">{title}</strong> : null}
        {children ? <div className="ui-alert-body">{children}</div> : null}
      </div>
      {action ? <div className="ui-alert-action">{action}</div> : null}
    </div>
  );
}
