// Cascade layers for the app's CSS. The order statement lives in src/styles/layers.css;
// this module mirrors it for tooling and wraps third-party CSS that the bundle imports.

/** Layer order, lowest priority first. Must match src/styles/layers.css. */
export const CSS_LAYERS = ["reset", "tokens", "primitives", "patterns", "features", "overrides"];

/**
 * Third-party CSS imported through JavaScript (Monaco's editor styles). It joins `features`,
 * the layer that holds the app's feature CSS, so it keeps competing with that CSS by
 * specificity and order exactly as before layers existed. Unlayered, it would beat every
 * layered rule regardless of specificity.
 */
export const VENDOR_CSS_LAYER = "features";
export const VENDOR_CSS_PATTERN = /[\\/]node_modules[\\/]monaco-editor[\\/].*\.css(?:$|\?)/;

export function wrapInLayer(css, layer) {
  return `@layer ${layer} {\n${css}\n}\n`;
}

export function vendorCssLayerPlugin() {
  return {
    name: "candlescope:vendor-css-layer",
    enforce: "pre",
    transform(code, id) {
      if (!VENDOR_CSS_PATTERN.test(id)) return null;
      return { code: wrapInLayer(code, VENDOR_CSS_LAYER), map: null };
    },
  };
}
