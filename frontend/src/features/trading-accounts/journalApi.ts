import type { tradingApi } from "./tradingApi.js";

/** Journal-only transport. Read-only accounts use the protected desktop session. */
export type JournalApi = Pick<typeof tradingApi,
  "trade" | "excursion" | "entry" | "createEntry" | "saveEntry" | "linkEntry" | "addSnapshot"> & {
  snapshotImageUrl(id: string): string | Promise<string>;
};
