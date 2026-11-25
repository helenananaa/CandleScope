/** External navigation is restricted to the support destinations shown in About and the update notice. */
export function isSupportLink(value) {
  try {
    if (typeof value !== "string" || value.length > 8000) return false;
    const url = new URL(value);
    if (url.origin !== "https://github.com" || url.username || url.password) return false;
    const root = "/helenananaa/CandleScope";
    // The update notice links to one app release's page: tags are exactly vMAJOR.MINOR.PATCH.
    const releasePage = url.pathname.startsWith(`${root}/releases/tag/`)
      && /^v\d+\.\d+\.\d+$/.test(url.pathname.slice(`${root}/releases/tag/`.length));
    if (!releasePage && ![root, `${root}/releases`, `${root}/blob/main/LICENSE`, `${root}/issues/new`].includes(url.pathname)) return false;
    if (url.pathname === `${root}/issues/new`) return [...url.searchParams.keys()].every(key => key === "body");
    return !url.search && (!url.hash || url.hash === "#readme");
  } catch { return false; }
}
