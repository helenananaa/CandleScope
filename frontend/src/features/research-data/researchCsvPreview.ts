export const CSV_FIELDS = ["time", "open", "high", "low", "close", "volume"] as const;
export type CsvField = typeof CSV_FIELDS[number];
export type CsvColumns = Record<CsvField, string>;
export interface CsvPreview { headers: string[]; rows: string[][]; suggested: CsvColumns; }

export function parseResearchCsvPreview(text: string): CsvPreview {
  const records: string[][] = [];
  let row: string[] = [], field = "", quoted = false;
  for (let index = text.charCodeAt(0) === 0xfeff ? 1 : 0; index < text.length && records.length < 6; index++) {
    const char = text[index];
    if (char === '"') {
      if (quoted && text[index + 1] === '"') { field += '"'; index++; }
      else quoted = !quoted;
    } else if (char === "," && !quoted) { row.push(field); field = ""; }
    else if ((char === "\n" || char === "\r") && !quoted) {
      row.push(field); if (row.some((value) => value !== "")) records.push(row);
      row = []; field = "";
      if (char === "\r" && text[index + 1] === "\n") index++;
    } else field += char;
  }
  const headers = records.shift() ?? [];
  if (headers.length < 5 || headers.some((header) => !header.trim()) || new Set(headers.map((header) => header.trim().toLowerCase())).size !== headers.length) {
    throw new Error("CSV needs a unique comma-separated header and at least five columns");
  }
  const aliases: Record<CsvField, string[]> = { time: ["time", "timestamp", "datetime", "date", "open_time", "open time", "t"], open: ["open", "o"], high: ["high", "h"], low: ["low", "l"], close: ["close", "c"], volume: ["volume", "vol", "qty"] };
  const suggested = Object.fromEntries(CSV_FIELDS.map((key) => {
    const matches = headers.filter((header) => aliases[key].includes(header.trim().toLowerCase()));
    return [key, matches.length === 1 ? matches[0] : ""];
  })) as CsvColumns;
  return { headers, rows: records, suggested };
}

export function validCsvColumns(columns: CsvColumns, headers: readonly string[]): boolean {
  const values = CSV_FIELDS.filter((key) => key !== "volume" || columns[key]).map((key) => columns[key]);
  return values.every((value) => headers.includes(value)) && new Set(values).size === values.length;
}
