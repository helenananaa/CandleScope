import { renderExportImage } from "../export/exportService.js";
import type { ExportSnapshot } from "../export/exportTypes.js";

function blobToDataUrl(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(reader.error ?? new Error("image read failed"));
    reader.readAsDataURL(blob);
  });
}

/** PNG of the chart as currently shown, for a journal snapshot. */
export async function captureChartPng(snapshot: ExportSnapshot | null): Promise<string | null> {
  if (!snapshot) return null;
  const result = await renderExportImage(snapshot, {
    scope: "chart",
    format: "png",
    scale: 1,
    watermarkEnabled: false,
  });
  return blobToDataUrl(result.blob);
}
