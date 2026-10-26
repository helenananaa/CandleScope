function bridge() {
  const native = window.candlescopeDesktop;
  if (!native?.controlEnabled || !native.controlFile) throw new Error("CONTROL_FILES_UNAVAILABLE");
  return native.controlFile;
}
function encode(bytes: Uint8Array): string {
  let value = ""; for (const byte of bytes) value += String.fromCharCode(byte); return btoa(value);
}
export async function readControlFile(fileRef: string): Promise<File> {
  const call = bridge();
  const first = await call("read", { fileRef, offset: 0 });
  if (!first.committed || first.size > 33554432) throw new Error("FILE_UNAVAILABLE");
  const bytes = new Uint8Array(first.size);
  for (let offset = 0; offset < bytes.length;) {
    const part = offset === 0 ? first : await call("read", { fileRef, offset });
    const decoded = Uint8Array.from(atob(part.data ?? ""), (c) => c.charCodeAt(0));
    if (!decoded.length || decoded.length > bytes.length - offset) throw new Error("FILE_INCOMPLETE");
    bytes.set(decoded, offset); offset += decoded.length;
  }
  return new File([bytes], first.name, { type: first.mimeType });
}
export async function publishControlFile(blob: Blob, name: string) {
  if (blob.size > 33554432) throw new Error("FILE_BUDGET");
  const call = bridge();
  const bytes = new Uint8Array(await blob.arrayBuffer());
  const sha256 = [...new Uint8Array(await crypto.subtle.digest("SHA-256", bytes))].map((n) => n.toString(16).padStart(2, "0")).join("");
  const entry = await call("begin", { uploadId: crypto.randomUUID(), name, mimeType: blob.type, size: bytes.length, sha256 });
  try {
    for (let offset = 0; offset < bytes.length; offset += entry.chunkBytes) {
      await call("write", { fileRef: entry.fileRef, offset, data: encode(bytes.subarray(offset, offset + entry.chunkBytes)) });
    }
    return await call("commit", { fileRef: entry.fileRef });
  } catch (error) { await call("remove", { fileRef: entry.fileRef }).catch(() => undefined); throw error; }
}
