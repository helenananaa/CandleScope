import { useId, useState } from "react";
import { Input } from "../../components/ui/Field.js";

export function IndicatorNumberInput({ value, min, max, step, title, disabled, onCommit }: {
  value: string | number;
  min?: number | undefined;
  max?: number | undefined;
  step: number;
  title: string;
  disabled?: boolean;
  onCommit(value: number): void;
}) {
  const errorId = useId();
  const [error, setError] = useState("");
  const commit = (input: HTMLInputElement) => {
    if (!input.validity.valid || !Number.isFinite(input.valueAsNumber)) {
      setError(input.validationMessage);
      return;
    }
    setError("");
    if (input.valueAsNumber !== Number(value)) onCommit(input.valueAsNumber);
  };
  return (
    <div className="indicator-number-input">
      <Input
        size="sm"
        title={title}
        type="number"
        disabled={disabled}
        required
        defaultValue={value}
        min={min}
        max={max}
        step={step}
        aria-invalid={Boolean(error)}
        aria-describedby={error ? errorId : undefined}
        onChange={() => setError("")}
        onBlur={(event) => commit(event.currentTarget)}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            event.preventDefault();
            commit(event.currentTarget);
          }
        }}
      />
      {error && <div id={errorId} role="alert" className="ui-field-error">{error}</div>}
    </div>
  );
}
