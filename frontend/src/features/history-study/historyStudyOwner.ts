/** Workspace IDs may contain Unicode, slashes and colons. Encode the tuple,
 * rather than concatenate ambiguous names or put decoded slashes in a route. */
export function historyStudyOwner(workspaceId: string, cellId: string): string {
  const bytes = new TextEncoder().encode(JSON.stringify([workspaceId, cellId]));
  return btoa(String.fromCharCode(...bytes)).replaceAll("+", "-").replaceAll("/", "_").replaceAll("=", "");
}
