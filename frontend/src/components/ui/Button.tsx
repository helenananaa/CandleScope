import type { ButtonHTMLAttributes, ReactNode } from "react";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: "sm" | "md";
  icon?: ReactNode;
}

/** Shared button; styles live in src/styles/components.css (.ui-btn). */
export function Button({
  variant = "secondary",
  size = "md",
  icon,
  className,
  type = "button",
  children,
  ...rest
}: ButtonProps) {
  const classes = [
    "ui-btn",
    variant === "secondary" ? null : `ui-btn-${variant}`,
    size === "sm" ? "ui-btn-sm" : null,
    className,
  ].filter(Boolean).join(" ");
  return (
    <button type={type} className={classes} {...rest}>
      {icon ? <span aria-hidden="true" style={{ display: "inline-flex" }}>{icon}</span> : null}
      {children}
    </button>
  );
}
