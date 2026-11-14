import type { PropsWithChildren, ReactNode } from "react";

/** One section of a research tool's side panels: its name, the object it shows, then its controls. */
export default function ResearchPanelFrame({
  title,
  eyebrow,
  trailing = null,
  children,
  className = "",
}: PropsWithChildren<{
  /** The object the panel shows (a strategy, dataset, run…). */
  title: string;
  /** The panel's name (策略, 数据, 执行…). */
  eyebrow: string;
  trailing?: ReactNode;
  className?: string;
}>) {
  return (
    <section className={`research-panel ${className}`.trim()}>
      <header className="research-panel-head">
        <div>
          <h3>{eyebrow}</h3>
          {title ? <p title={title}>{title}</p> : null}
        </div>
        {trailing}
      </header>
      <div className="research-panel-body">{children}</div>
    </section>
  );
}
