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

export interface ControlButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  size?: ControlSize;
  /** Shows the control as on, e.g. while its panel is open. */
  active?: boolean;
  icon?: ReactNode;
  ref?: Ref<HTMLButtonElement>;
}

/** Toolbar control: the pills, pickers and toggles in bars and headers (.ui-control). */
export function ControlButton({ size = "md", active = false, icon, className, type = "button", children, ref, ...rest }: ControlButtonProps) {
  const classes = ["ui-control", size === "sm" ? "ui-control-sm" : null, active ? "is-active" : null, className].filter(Boolean).join(" ");
  return (
    <button ref={ref} type={type} className={classes} {...rest}>
      {icon ? <span className="ui-control-icon" aria-hidden="true">{icon}</span> : null}
      {children}
    </button>
  );
}

export interface OptionButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  /** `card`: a bordered tile (a choice with a title and description); `row`: a list row. */
  variant?: "card" | "row";
  /**
   * Chosen. Reported as aria-pressed, or as aria-selected when the button is an option or a tab
   * (role="option" / role="tab").
   */
  selected?: boolean;
  ref?: Ref<HTMLButtonElement>;
}

/**
 * A block-level choice: a template, a setting with a description, a row in a list. The primitive
 * owns the box, colour and states; the feature lays out what is inside (title, description, glyph).
 */
export function OptionButton({ variant = "card", selected, role, className, type = "button", children, ref, ...rest }: OptionButtonProps) {
  const state = selected === undefined ? {} : role === "option" || role === "tab" ? { "aria-selected": selected } : { "aria-pressed": selected };
  return (
    <button ref={ref} type={type} role={role} className={["ui-option", `ui-option-${variant}`, className].filter(Boolean).join(" ")} {...state} {...rest}>
      {children}
    </button>
  );
}
