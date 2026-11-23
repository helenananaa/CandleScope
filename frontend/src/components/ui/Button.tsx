import type { ButtonHTMLAttributes, ReactNode, Ref } from "react";
import { buttonClassName } from "./helpers.js";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
export type ControlSize = "sm" | "md";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ControlSize;
  icon?: ReactNode;
  /** Stretch to the container's width (dialog footers, narrow panels). */
  fullWidth?: boolean;
  ref?: Ref<HTMLButtonElement>;
}

/** Shared button; styles live in button.css (primitives layer). */
export function Button({ variant = "secondary", size = "md", icon, fullWidth = false, className, type = "button", children, ref, ...rest }: ButtonProps) {
  return (
    <button ref={ref} type={type} className={buttonClassName({ variant, size, fullWidth, className })} {...rest}>
      {icon ? <span className="ui-btn-icon" aria-hidden="true">{icon}</span> : null}
      {children}
    </button>
  );
}

export interface IconButtonProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, "children"> {
  /** Accessible name; also shown as the tooltip. */
  label: string;
  icon: ReactNode;
  size?: ControlSize;
  /** `danger` turns red on hover, for delete and remove. */
  variant?: "ghost" | "secondary" | "danger";
  /** Toggle buttons report their state. */
  pressed?: boolean;
  /** A small mark in the bottom-right corner, e.g. that a tool has variants. */
  indicator?: ReactNode;
  ref?: Ref<HTMLButtonElement>;
}

/** Square icon-only button. */
export function IconButton({ label, icon, size = "md", variant = "ghost", pressed, indicator, className, type = "button", ref, ...rest }: IconButtonProps) {
  const classes = ["ui-icon-btn", size === "sm" ? "ui-icon-btn-sm" : null, variant === "ghost" ? null : `ui-icon-btn-${variant}`, className].filter(Boolean).join(" ");
  return (
    <button ref={ref} type={type} className={classes} aria-label={label} title={label} aria-pressed={pressed} {...rest}>
      <span aria-hidden="true">{icon}</span>
      {indicator ? <span className="ui-icon-btn-indicator" aria-hidden="true">{indicator}</span> : null}
    </button>
  );
}
