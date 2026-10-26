import { useEffect, useRef } from "react";
import { formatUtcReplayStartInput, parseUtcReplayStartInput } from "../trainingHubModel.js";

/** Preserve native date segments while an incomplete edit is not a valid UTC instant. */
export default function UtcReplayStartInput({ value, onChange, ...attributes }: {
  readonly value: number | null;
  readonly onChange: (value: number | null) => void;
  readonly disabled?: boolean;
  readonly "data-training-field"?: string;
}) {
  const input = useRef<HTMLInputElement>(null);
  const published = useRef(value);
  useEffect(() => {
    // Apply external changes (preset, restored draft), but do not round-trip a
    // locally typed intermediate year such as 0002 through the UTC validator.
    if (value !== published.current && input.current !== null) {
      input.current.value = formatUtcReplayStartInput(value);
      published.current = value;
    }
  }, [value]);
  return <input {...attributes} ref={input} type="datetime-local" step={60}
    defaultValue={formatUtcReplayStartInput(value)}
    onChange={(event) => {
      const next = parseUtcReplayStartInput(event.currentTarget.value);
      published.current = next;
      onChange(next);
    }} />;
}
