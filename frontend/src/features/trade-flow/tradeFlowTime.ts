import { chartTimeZoneOption } from "../../chart-adapter/chartPaneLifecycle.js";
import { getDateTimeLocale } from "../../i18n/index.js";

// Trade times follow the chart timezone setting so the tape lines up with the time axis.

const TAPE_TIME_OPTIONS: Intl.DateTimeFormatOptions = {
  hour12: false,
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
};
let tapeTimeFormat: { key: string; format: Intl.DateTimeFormat } | null = null;

function tapeTimeFormatter(timezone: string | undefined): Intl.DateTimeFormat {
  const locale = getDateTimeLocale();
  const timeZone = chartTimeZoneOption(timezone);
  const key = `${locale}|${timeZone ?? ""}`;
  if (tapeTimeFormat?.key !== key) {
    let format: Intl.DateTimeFormat;
    try {
      format = new Intl.DateTimeFormat(locale, timeZone ? { ...TAPE_TIME_OPTIONS, timeZone } : TAPE_TIME_OPTIONS);
    } catch {
      // An unknown zone name must not take the rail down; show system time instead.
      format = new Intl.DateTimeFormat(locale, TAPE_TIME_OPTIONS);
    }
    tapeTimeFormat = { key, format };
  }
  return tapeTimeFormat.format;
}

/** HH:MM:SS.mmm in the chart's timezone; milliseconds are the same in every zone. */
export function formatTapeTime(value: number, timezone?: string): string {
  const date = new Date(value);
  const base = tapeTimeFormatter(timezone).format(date);
  return `${base}.${String(date.getUTCMilliseconds()).padStart(3, "0")}`;
}

export function formatLastTradeTime(value: number, timezone: string | undefined): string {
  const timeZone = chartTimeZoneOption(timezone);
  try {
    return new Date(value).toLocaleString(getDateTimeLocale(), timeZone ? { hour12: false, timeZone } : { hour12: false });
  } catch {
    return new Date(value).toLocaleString(getDateTimeLocale(), { hour12: false });
  }
}
