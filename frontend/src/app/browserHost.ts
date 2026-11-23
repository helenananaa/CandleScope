/**
 * Whether this build is the web version: the static site that runs the Python
 * engine in the browser (see browser/host). Features that need the desktop app
 * say so there instead of failing.
 */
export function browserHost(): boolean {
  return import.meta.env?.VITE_BROWSER_PYTHON === "1";
}
