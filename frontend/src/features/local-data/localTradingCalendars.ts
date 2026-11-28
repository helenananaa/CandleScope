import { t } from "../../i18n/index.js";

/**
 * ADR-DATA-002 D2e: trading calendars an imported CSV can declare. Each one
 * labels daily bars at 00:00 UTC on the trading date, so its imports use the
 * listed interval and UTC.
 */
export const CN_A_SHARE_CALENDAR_ID = "cn.a-share.exchange-date.utc";

export interface LocalImportCalendar {
  id: string;
  interval: "1d";
  timezone: "UTC";
}

export const LOCAL_IMPORT_CALENDARS: readonly LocalImportCalendar[] = [
  { id: CN_A_SHARE_CALENDAR_ID, interval: "1d", timezone: "UTC" },
];

export function findLocalImportCalendar(id: string | null | undefined): LocalImportCalendar | null {
  return LOCAL_IMPORT_CALENDARS.find((calendar) => calendar.id === id) ?? null;
}

export function localCalendarLabel(id: string): string {
  return id === CN_A_SHARE_CALENDAR_ID ? t("local.calendar.cnAShare") : id;
}
