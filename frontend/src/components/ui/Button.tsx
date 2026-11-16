import type { ButtonHTMLAttributes, ReactNode } from "react";
import { buttonClassName } from "./helpers.js";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
export type ControlSize = "sm" | "md";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ControlSize;
  icon?: ReactNode;
  /** Stretch to the container's width (dialog footers, narrow panels). */
  fullWidth?: boolean;
}

/** Shared button; styles live in button.css (primitives layer). */
export function Button({ variant = "secondary", size = "md", icon, fullWidth = false, className, type = "button", children, ...rest }: ButtonProps) {
  return (
    <button type={type} className={buttonClassName({ variant, size, fullWidth, className })} {...rest}>
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
  variant?: "ghost" | "secondary";
  /** Toggle buttons report their state. */
  pressed?: boolean;
}

/** Square icon-only button. */
export function IconButton({ label, icon, size = "md", variant = "ghost", pressed, className, type = "button", ...rest }: IconButtonProps) {
  const classes = ["ui-icon-btn", size === "sm" ? "ui-icon-btn-sm" : null, variant === "secondary" ? "ui-icon-btn-secondary" : null, className].filter(Boolean).join(" ");
  return (
    <button type={type} className={classes} aria-label={label} title={label} aria-pressed={pressed} {...rest}>
      <span aria-hidden="true">{icon}</span>
    </button>
  );
}
