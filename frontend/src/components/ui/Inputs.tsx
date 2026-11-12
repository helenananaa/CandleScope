import { useId, useState, type DragEvent, type ReactNode } from "react";
import { Input, type InputProps } from "./Field.js";
import { fromDateTimeInputValue, toDateTimeInputValue } from "./helpers.js";

export interface DateTimeInputProps extends Omit<InputProps, "type" | "value" | "onChange" | "defaultValue"> {
  value: number | null;
  onChange: (epochMs: number | null) => void;
  /** Show and edit the time in UTC (default) or in the browser's time zone. */
  utc?: boolean;
  /** Edit seconds as well as minutes. */
  seconds?: boolean;
  /** Visible zone label after the control. */
  zoneLabel?: string;
}

/** Date and time in an explicit zone; the zone is always shown next to the value. */
export function DateTimeInput({ value, onChange, utc = true, seconds = false, zoneLabel, className, ...rest }: DateTimeInputProps) {
  const zone = zoneLabel ?? (utc ? "UTC" : Intl.DateTimeFormat().resolvedOptions().timeZone);
  return (
    <span className={["ui-datetime", className].filter(Boolean).join(" ")}>
      <Input
        {...rest}
        type="datetime-local"
        step={seconds ? 1 : 60}
        value={toDateTimeInputValue(value, utc, seconds)}
        onChange={(event) => onChange(fromDateTimeInputValue(event.target.value, utc))}
      />
      <span className="ui-datetime-zone">{zone}</span>
    </span>
  );
}

export interface FileDropProps {
  label: ReactNode;
  hint?: ReactNode;
  accept?: string;
  multiple?: boolean;
  disabled?: boolean;
  onFiles: (files: File[]) => void;
  className?: string;
}

/** Drop zone that is also a file picker (click or keyboard). */
export function FileDrop({ label, hint, accept, multiple = false, disabled = false, onFiles, className }: FileDropProps) {
  const id = useId();
  const [dragging, setDragging] = useState(false);
  const take = (list: FileList | null) => {
    const files = list ? [...list] : [];
    if (files.length && !disabled) onFiles(multiple ? files : files.slice(0, 1));
  };
  const onDrop = (event: DragEvent<HTMLLabelElement>) => {
    event.preventDefault();
    setDragging(false);
    take(event.dataTransfer.files);
  };
  return (
    <label
      htmlFor={id}
      className={["ui-file-drop", className].filter(Boolean).join(" ")}
      data-dragging={dragging ? "true" : undefined}
      data-disabled={disabled ? "true" : undefined}
      onDragOver={(event) => { if (!disabled) { event.preventDefault(); setDragging(true); } }}
      onDragLeave={() => setDragging(false)}
      onDrop={onDrop}
    >
      <input id={id} type="file" className="ui-file-drop-input" accept={accept} multiple={multiple} disabled={disabled}
        onChange={(event) => { take(event.target.files); event.target.value = ""; }} />
      <span className="ui-file-drop-label">{label}</span>
      {hint ? <span className="ui-file-drop-hint">{hint}</span> : null}
    </label>
  );
}
