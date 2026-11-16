/** Whether the person asked their system for less motion. Script-driven motion (smooth scrolling,
 * editor caret animation) follows it the way CSS does through the rule in styles/reset.css. */
export function prefersReducedMotion(): boolean {
  return typeof window !== "undefined" && typeof window.matchMedia === "function"
    && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/** `behavior` for scrollTo / scrollIntoView: smooth unless reduced motion is asked for. */
export function scrollBehavior(): ScrollBehavior {
  return prefersReducedMotion() ? "auto" : "smooth";
}
