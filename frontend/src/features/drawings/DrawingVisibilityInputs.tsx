import { t } from "../../i18n/index.js";
import { drawingVisibleAtInterval } from "./drawingVisibility.js";

const intervals = ["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d", "3d", "1w", "1M"];
export default function DrawingVisibilityInputs({ value, currentInterval, onChange }: {
  value: readonly string[] | null | undefined;
  currentInterval: string;
  onChange(value: readonly string[] | null): void;
}) {
  const all = value == null;
  const choices = [...new Set([...intervals, currentInterval, ...(value ?? [])])];
  return <fieldset className="drawing-visibility-fields">
    <legend>{t("drawing.visibility.title")}</legend>
    <label><input type="checkbox" checked={all} onChange={event => onChange(event.target.checked ? null : [currentInterval])} />{t("drawing.visibility.all")}</label>
    {!all && <div className="drawing-visibility-grid">{choices.map(interval => <label key={interval}>
      <input type="checkbox" checked={value.includes(interval)} onChange={event => onChange(event.target.checked ? [...value, interval] : value.filter(item => item !== interval))} />
      {interval.replace(/h$/, "H").replace(/d$/, "D").replace(/w$/, "W")}
    </label>)}</div>}
    {!all && value.length === 0 && <p className="drawing-field-error" role="alert">{t("drawing.visibility.required")}</p>}
    {!all && value.length > 0 && !drawingVisibleAtInterval({ visibleIntervals: value }, currentInterval) && <p className="drawing-control-caption" role="status">{t("drawing.visibility.hiddenHere")}</p>}
  </fieldset>;
}
