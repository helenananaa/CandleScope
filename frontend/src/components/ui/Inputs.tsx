import { useId, useRef, useState, type DragEvent, type ReactNode } from "react";
import { t } from "../../i18n/index.js";
import { Icon } from "../icons/Icon.js";
import { Input, type InputProps } from "./Field.js";
import { fromDateTimeInputValue, fromDateTimeText, toDateTimeInputValue, toDateTimeText } from "./helpers.js";

export interface DateTimeInputProps extends Omit<InputProps, "type" | "value" | "onChange" | "defaultValue"> {
  value: number | null;
  onChange: (epochMs: number | null) => void;
  /** Show and edit the time in UTC (default) or in the browser's time zone. */
  utc?: boolean;
  /** Edit seconds as well as minutes. */
  seconds?: boolean;
  /** Visible zone label after the control; false only when the field's label already names the zone. */
  zoneLabel?: string | false;
}

/**
 * Date and time in an explicit zone, written the same way in every locale (`2026-01-02 03:04`).
 * The native control would follow the browser's locale instead of the app's, so the text field is
 * the control and the calendar button opens the browser's picker. The zone is always shown.
 * While the text does not parse, `onChange` receives null and the typed text stays as it is.
 */
export function DateTimeInput({ value, onChange, utc = true, seconds = false, zoneLabel, className, disabled, onBlur, ...rest }: DateTimeInputProps) {
  const zone = zoneLabel ?? (utc ? "UTC" : Intl.DateTimeFormat().resolvedOptions().timeZone);
  const pickerRef = useRef<HTMLInputElement>(null);
  // Text the user is typing, kept until it parses and the field loses focus, or the value changes from outside.
  const [draft, setDraft] = useState<{ text: string; emitted: number | null } | null>(null);
  const editing = draft !== null && draft.emitted === value;
  const text = editing ? draft.text : toDateTimeText(value, utc, seconds);
  const invalid = editing && draft.text.trim() !== "" && draft.emitted === null;
  const openPicker = () => {
    const picker = pickerRef.current;
    if (!picker || disabled) return;
    try { picker.showPicker(); } catch { picker.focus(); }
  };
  return (
    <span className={["ui-datetime", className].filter(Boolean).join(" ")} data-disabled={disabled ? "true" : undefined}>
      <span className="ui-datetime-control">
        <Input
          aria-invalid={invalid || undefined}
          {...rest}
          type="text"
          inputMode="numeric"
          autoComplete="off"
          spellCheck={false}
          placeholder={seconds ? "YYYY-MM-DD HH:mm:ss" : "YYYY-MM-DD HH:mm"}
          disabled={disabled}
          value={text}
          onChange={(event) => {
            const next = fromDateTimeText(event.target.value, utc);
            setDraft({ text: event.target.value, emitted: next });
            onChange(next);
          }}
          onBlur={(event) => {
            if (editing && draft.emitted !== null) setDraft(null);
            onBlur?.(event);
          }}
        />
        <button type="button" className="ui-datetime-picker" aria-label={t("common.pickDateTime")} title={t("common.pickDateTime")}
          disabled={disabled} onClick={openPicker}>
          <Icon name="calendar" size={15} />
        </button>
        <input ref={pickerRef} type="datetime-local" className="ui-datetime-native" tabIndex={-1} aria-hidden="true"
          step={seconds ? 1 : 60} disabled={disabled} value={toDateTimeInputValue(value, utc, seconds)}
          onChange={(event) => {
            setDraft(null);
            onChange(fromDateTimeInputValue(event.target.value, utc));
          }} />
      </span>
      {zone === false ? null : <span className="ui-datetime-zone">{zone}</span>}
    </span>
  );
}

export interface FileDropProps {
  label: ReactNode;
  hint?: ReactNode;
  accept?: string;
  multiple?: boolean;
  disabled?: boolean;
  /** One row with an icon, for narrow panels. */
  compact?: boolean;
  onFiles: (files: File[]) => void;
  className?: string;
}

/** Drop zone that is also a file picker (click or keyboard). */
export function FileDrop({ label, hint, accept, multiple = false, disabled = false, compact = false, onFiles, className }: FileDropProps) {
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
      className={["ui-file-drop", compact ? "ui-file-drop-compact" : null, className].filter(Boolean).join(" ")}
      data-dragging={dragging ? "true" : undefined}
      data-disabled={disabled ? "true" : undefined}
      onDragOver={(event) => { if (!disabled) { event.preventDefault(); setDragging(true); } }}
      onDragLeave={() => setDragging(false)}
      onDrop={onDrop}
    >
      <input id={id} type="file" className="ui-file-drop-input" accept={accept} multiple={multiple} disabled={disabled}
        onChange={(event) => { take(event.target.files); event.target.value = ""; }} />
      {compact ? <span className="ui-file-drop-icon"><Icon name="upload" size={16} /></span> : null}
      <span className="ui-file-drop-label">{label}</span>
      {hint ? <span className="ui-file-drop-hint">{hint}</span> : null}
    </label>
  );
}
