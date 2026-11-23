import { writeFile, rename, unlink } from "node:fs/promises";
import { randomUUID } from "node:crypto";

export async function writeMarker(markerPath, value) {
  const temporary = `${markerPath}.${process.pid}.${randomUUID()}.tmp`;
  try {
    // A process can exit during either write. Never truncate the last complete marker.
    await writeFile(temporary, JSON.stringify(value), { encoding: "utf8", flush: true });
    await rename(temporary, markerPath);
  } catch (error) {
    await unlink(temporary).catch(() => {});
    throw error;
  }
}
