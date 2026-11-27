// Which GitHub release, if any, is a newer CandleScope app than this one.
// Pure functions: no fetch, no storage, no clock.

export const RELEASE_REPOSITORY = "helenananaa/CandleScope";
/** Newest first. The repository also holds plugin releases, so `/releases/latest` can name one of those. */
export const RELEASES_API_URL = `https://api.github.com/repos/${RELEASE_REPOSITORY}/releases?per_page=30`;
const RELEASE_PAGE_BASE = `https://github.com/${RELEASE_REPOSITORY}/releases/tag/`;

/** App releases are tagged `v1.2.3`; plugin releases (`pine-v0.3.3`) and release candidates are not. */
const APP_RELEASE_TAG = /^v(\d+)\.(\d+)\.(\d+)$/;
/** This app's own version: `1.2.3`, optionally `-rc.1` and/or `+build`. */
const APP_VERSION_PATTERN = /^(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$/;

export interface AvailableRelease {
  /** `1.2.3`, without the `v`. */
  version: string;
  /** That release's page on GitHub. */
  url: string;
}

interface ParsedVersion {
  core: readonly [number, number, number];
  prerelease: boolean;
}

function parseCore(match: RegExpExecArray | null): readonly [number, number, number] | null {
  if (!match) return null;
  const core = [Number(match[1]), Number(match[2]), Number(match[3])] as const;
  return core.every(Number.isSafeInteger) ? core : null;
}

function parseAppVersion(value: string): ParsedVersion | null {
  const match = APP_VERSION_PATTERN.exec(value);
  const core = parseCore(match);
  return core ? { core, prerelease: Boolean(match?.[4]) } : null;
}

/** The version a stable app release tag names (`v1.2.3` → `1.2.3`), or null for any other tag. */
export function appReleaseVersion(tag: unknown): string | null {
  if (typeof tag !== "string") return null;
  const core = parseCore(APP_RELEASE_TAG.exec(tag));
  return core ? core.join(".") : null;
}

/**
 * Semver order of two versions: negative when `a` is older, 0 when equal, positive when newer.
 * A prerelease sorts before its release (`1.1.0-rc.1` < `1.1.0`); prereleases of one version tie.
 * Null when either is not a version.
 */
export function compareVersions(a: string, b: string): number | null {
  const left = parseAppVersion(a);
  const right = parseAppVersion(b);
  if (!left || !right) return null;
  for (let index = 0; index < 3; index++) {
    const difference = left.core[index]! - right.core[index]!;
    if (difference) return Math.sign(difference);
  }
  return Number(right.prerelease) - Number(left.prerelease);
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

/**
 * The newest published, non-draft, non-prerelease app release in a GitHub `GET /releases` response.
 * Only the version is read from the response: the page link is built from it, never taken from it.
 * Throws when the response is not a list of releases.
 */
export function newestAppRelease(payload: unknown): AvailableRelease | null {
  if (!Array.isArray(payload)) throw new TypeError("GitHub releases response is not a list");
  let newest: string | null = null;
  for (const release of payload) {
    if (!isRecord(release) || release.draft !== false || release.prerelease !== false) continue;
    if (typeof release.published_at !== "string" || !release.published_at) continue;
    const version = appReleaseVersion(release.tag_name);
    if (version && (newest === null || compareVersions(version, newest)! > 0)) newest = version;
  }
  return newest === null ? null : { version: newest, url: `${RELEASE_PAGE_BASE}v${newest}` };
}

/** The release to tell the user about: newer than `currentVersion` and not skipped. */
export function releaseToOffer(
  release: AvailableRelease | null,
  currentVersion: string,
  skippedVersions: readonly string[],
): AvailableRelease | null {
  if (!release || skippedVersions.includes(release.version)) return null;
  const order = compareVersions(release.version, currentVersion);
  return order !== null && order > 0 ? release : null;
}
