import { DateTimeInput } from "../../../components/ui/index.js";

/**
 * A replay start instant in UTC, written `2026-01-02 03:04` in every locale (the native control
 * followed the browser's locale). While the text does not parse, onChange receives null and the
 * typed text stays, so a partly typed year is not erased.
 */
export default function UtcReplayStartInput({ value, onChange, ...attributes }: {
  readonly value: number | null;
  readonly onChange: (value: number | null) => void;
  readonly disabled?: boolean;
  readonly "data-training-field"?: string;
}) {
  // The field labels already say UTC; starts before 1970 are not valid replay instants.
  return <DateTimeInput {...attributes} value={value} onChange={onChange} zoneLabel={false} earliest={0} />;
}
