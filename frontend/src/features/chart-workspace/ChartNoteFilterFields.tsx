import { t } from "../../i18n/index.js";
import { normalizeChartAccountOverlay, type ChartAccountOverlaySettings } from "./chartAccountOverlaySettings.js";

export default function ChartNoteFilterFields({ value, onChange }: {
  value: ChartAccountOverlaySettings;
  onChange(settings: ChartAccountOverlaySettings): void;
}) {
  return <>
    <label>
      {t("replay.notes.markerSource")}
      <select value={value.noteSource ?? "all"} disabled={!value.notes}
        onChange={event => onChange(normalizeChartAccountOverlay({ ...value, noteSource: event.target.value }))}>
        <option value="all">{t("replay.notes.allMarkers")}</option>
        <option value="original">{t("replay.notes.original")}</option>
        <option value="review">{t("replay.notes.review")}</option>
      </select>
    </label>
    <label>
      {t("replay.notes.markerFilter")}
      <select value={value.noteFilter ?? "all"} disabled={!value.notes}
        onChange={event => onChange(normalizeChartAccountOverlay({ ...value, noteFilter: event.target.value }))}>
        <option value="all">{t("replay.notes.allMarkers")}</option>
        <option value="linked">{t("replay.notes.linkedMarkers")}</option>
        <option value="screenshots">{t("replay.notes.screenshotMarkers")}</option>
      </select>
    </label>
  </>;
}
