import { useId, useState } from "react";

export function IndicatorNumberInput({ value, min, max, step, title, onCommit }: {
  value: string | number;
  min?: number | undefined;
  max?: number | undefined;
  step: number;
  title: string;
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
    <div>
      <input
        className="indicator-param-input"
        title={title}
        type="number"
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
      {error && <div id={errorId} role="alert" style={{ color: "var(--text-primary)", fontSize: 12 }}>{error}</div>}
    </div>
  );
}
