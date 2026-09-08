import assert from "node:assert/strict";
import test from "node:test";
import { parseResearchCsvPreview, validCsvColumns } from "../researchCsvPreview.js";

test("CSV preview handles BOM, quoted commas, escaped quotes and CRLF without changing source fields", () => {
  const preview = parseResearchCsvPreview('\ufeff"Date",Open,High,Low,Close,"Note, text"\r\n1704067200,1,3,1,2,"say ""hello"""\r\n');
  assert.equal(preview.headers[5], "Note, text");
  assert.equal(preview.rows[0]?.[5], 'say "hello"');
  assert.equal(preview.suggested.time, "Date");
  assert.ok(validCsvColumns(preview.suggested, preview.headers));
  assert.equal(validCsvColumns({ ...preview.suggested, close: "Open" }, preview.headers), false);
});

test("CSV preview rejects duplicate headers and requires explicit mappings for unknown names", () => {
  assert.throws(() => parseResearchCsvPreview('time,open,high,low,open\n1,1,1,1,1\n'));
  const preview = parseResearchCsvPreview('日期,开,高,低,收\n1,1,3,1,2\n');
  assert.equal(validCsvColumns(preview.suggested, preview.headers), false);
  assert.equal(validCsvColumns({ time: "日期", open: "开", high: "高", low: "低", close: "收", volume: "" }, preview.headers), true);
});
