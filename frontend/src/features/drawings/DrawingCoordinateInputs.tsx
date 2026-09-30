import { t } from "../../i18n/index.js";
import { parseCoordinateTime, type CoordinateDraft } from "./drawingProperties.js";

export default function DrawingCoordinateInputs({ draft, onChange, disabled = false }: {
  disabled?: boolean;
  draft: readonly CoordinateDraft[];
  onChange(draft: CoordinateDraft[]): void;
}) {
  return <div className="drawing-coordinate-inputs">
    <p className="drawing-control-caption">{t("drawing.editor.utcHint")}</p>
    {draft.map((point, index) => <fieldset key={index} disabled={disabled}>
      <legend>{t("drawing.editor.point", { number: index + 1 })}</legend>
      <label><span>{t("drawing.editor.price")}</span><input type="number" step="any" value={point.price}
        aria-invalid={!point.price.trim() || !Number.isFinite(Number(point.price))}
        onChange={(event) => onChange(draft.map((item, i) => i === index ? { ...item, price: event.target.value } : item))} /></label>
      <label><span>{t("drawing.editor.timeUtc")}</span><input type="datetime-local" step="0.001" min="0001-01-01T00:00" max="9999-12-31T23:59:59.999" value={point.time}
        aria-invalid={parseCoordinateTime(point.time) === null}
        onChange={(event) => onChange(draft.map((item, i) => i === index ? { ...item, time: event.target.value } : item))} /></label>
    </fieldset>)}
  </div>;
}
