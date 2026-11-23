import { createContext, useContext, useId, type InputHTMLAttributes, type ReactNode, type Ref, type SelectHTMLAttributes, type TextareaHTMLAttributes } from "react";
import type { ControlSize } from "./Button.js";

interface FieldContextValue {
  id: string;
  describedBy: string | undefined;
  invalid: boolean;
  required: boolean;
}

const FieldContext = createContext<FieldContextValue | null>(null);

export interface FieldProps {
  label: ReactNode;
  /** Short help below the control; replaced by the error when there is one. */
  hint?: ReactNode;
  error?: ReactNode;
  required?: boolean;
  className?: string;
  children: ReactNode;
}

/** Label, control, hint and error. The control inside picks up the id and descriptions. */
export function Field({ label, hint, error, required = false, className, children }: FieldProps) {
  const id = useId();
  const messageId = `${id}-message`;
  const message = error ?? hint;
  return (
    <div className={["ui-field", className].filter(Boolean).join(" ")} data-invalid={error ? "true" : undefined}>
      <label className="ui-field-label" htmlFor={id}>
        {label}
        {required ? <span className="ui-field-required" aria-hidden="true">*</span> : null}
      </label>
      <FieldContext.Provider value={{ id, describedBy: message ? messageId : undefined, invalid: Boolean(error), required }}>
        {children}
      </FieldContext.Provider>
      {message ? <p id={messageId} className={error ? "ui-field-error" : "ui-field-hint"}>{message}</p> : null}
    </div>
  );
}

/** Props a control takes from its Field; explicit props win. */
function useFieldProps<T extends { id?: string | undefined; "aria-describedby"?: string | undefined; "aria-invalid"?: InputHTMLAttributes<HTMLInputElement>["aria-invalid"]; required?: boolean | undefined }>(props: T): T {
  const field = useContext(FieldContext);
  if (!field) return props;
  return {
    ...props,
    id: props.id ?? field.id,
    "aria-describedby": props["aria-describedby"] ?? field.describedBy,
    "aria-invalid": props["aria-invalid"] ?? (field.invalid || undefined),
    required: props.required ?? (field.required || undefined),
  };
}

const sizeClass = (base: string, size: ControlSize | undefined) => (size === "sm" ? `${base} ${base}-sm` : base);

export interface InputProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "size"> {
  size?: ControlSize;
  ref?: Ref<HTMLInputElement>;
}

export function Input({ size, className, ...rest }: InputProps) {
  const props = useFieldProps(rest);
  return <input className={[sizeClass("ui-input", size), className].filter(Boolean).join(" ")} {...props} />;
}

export type TextareaProps = TextareaHTMLAttributes<HTMLTextAreaElement>;

export function Textarea({ className, ...rest }: TextareaProps) {
  const props = useFieldProps(rest);
  return <textarea className={["ui-input", "ui-textarea", className].filter(Boolean).join(" ")} {...props} />;
}

export interface SelectProps extends Omit<SelectHTMLAttributes<HTMLSelectElement>, "size"> {
  size?: ControlSize;
}

/** Native select with a fixed-size chevron. */
export function Select({ size, className, children, ...rest }: SelectProps) {
  const props = useFieldProps(rest);
  return <select className={[sizeClass("ui-input", size), "ui-select", className].filter(Boolean).join(" ")} {...props}>{children}</select>;
}

export interface CheckboxProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "type"> {
  label: ReactNode;
  description?: ReactNode;
}

export function Checkbox({ label, description, className, ...rest }: CheckboxProps) {
  const descriptionId = useId();
  return (
    <label className={["ui-check", className].filter(Boolean).join(" ")}>
      <input type="checkbox" className="ui-check-input" aria-describedby={description ? descriptionId : undefined} {...rest} />
      <span className="ui-check-text">
        <span className="ui-check-label">{label}</span>
        {description ? <span id={descriptionId} className="ui-check-description">{description}</span> : null}
      </span>
    </label>
  );
}

export interface SwitchProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label: ReactNode;
  description?: ReactNode;
  disabled?: boolean;
  className?: string;
}

/** On/off setting that applies immediately. */
export function Switch({ checked, onChange, label, description, disabled = false, className }: SwitchProps) {
  const descriptionId = useId();
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-describedby={description ? descriptionId : undefined}
      disabled={disabled}
      className={["ui-switch", className].filter(Boolean).join(" ")}
      onClick={() => onChange(!checked)}
    >
      <span className="ui-switch-track" aria-hidden="true"><span className="ui-switch-thumb" /></span>
      <span className="ui-check-text">
        <span className="ui-check-label">{label}</span>
        {description ? <span id={descriptionId} className="ui-check-description">{description}</span> : null}
      </span>
    </button>
  );
}
