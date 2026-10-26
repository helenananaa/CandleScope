import { createHash, randomUUID } from "node:crypto";
import { open } from "node:fs/promises";
import path from "node:path";

export async function uploadFile(client, windowId, filename) {
  const handle = await open(filename, "r");
  let entry;
  try {
    const stat = await handle.stat();
    if (!stat.isFile() || stat.size > 33554432) throw new Error("FILE_BUDGET");
    const bytes = Buffer.alloc(stat.size);
    let offset = 0;
    while (offset < bytes.length) { const part = await handle.read(bytes, offset, bytes.length - offset, offset); if (!part.bytesRead) throw new Error("FILE_CHANGED"); offset += part.bytesRead; }
    if ((await handle.stat()).size !== stat.size) throw new Error("FILE_CHANGED");
    entry = await client.call("file.begin", { windowId, uploadId: randomUUID(), name: path.basename(filename), mimeType: "application/octet-stream", size: bytes.length, sha256: createHash("sha256").update(bytes).digest("hex") });
    for (offset = 0; offset < bytes.length; offset += entry.chunkBytes) await client.call("file.write", { windowId, fileRef: entry.fileRef, offset, data: bytes.subarray(offset, offset + entry.chunkBytes).toString("base64") });
    return await client.call("file.commit", { windowId, fileRef: entry.fileRef });
  } catch (error) { if (entry) await client.call("file.remove", { windowId, fileRef: entry.fileRef }).catch(() => {}); throw error; }
  finally { await handle.close(); }
}
export async function downloadFile(client, windowId, fileRef, filename) {
  const first = await client.call("file.read", { windowId, fileRef, offset: 0 });
  if (!first.committed || first.size > 33554432) throw new Error("FILE_UNAVAILABLE");
  const bytes = Buffer.alloc(first.size);
  for (let offset = 0; offset < bytes.length;) {
    const part = offset === 0 ? first : await client.call("file.read", { windowId, fileRef, offset });
    const chunk = Buffer.from(part.data, "base64");
    if (!chunk.length || chunk.length > bytes.length - offset) throw new Error("FILE_INCOMPLETE");
    chunk.copy(bytes, offset); offset += chunk.length;
  }
  if (createHash("sha256").update(bytes).digest("hex") !== first.sha256) throw new Error("FILE_HASH_MISMATCH");
  const handle = await open(filename, "wx");
  try { await handle.writeFile(bytes); } finally { await handle.close(); }
  return { ...first, data: undefined, output: filename };
}
