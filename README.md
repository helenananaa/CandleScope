# CandleScope website

Static introduction page for https://candlescope.app/, linking visitors to
https://github.com/helenananaa/CandleScope.

This independent `codex/website` branch contains only the public website. Product
source code remains on `main`. No build tool, dependencies, or backend is required.

## Files

| File | Purpose |
|---|---|
| `index.html` | Page content. Chinese is authored in the markup; each translatable element carries its English text in `data-en` (plus `data-en-href` / `data-en-aria` for links and labels). |
| `style.css` | Dark theme matching the product UI. Colors live as tokens on `:root`. |
| `assets/site.js` | Language switch, scroll reveals, and the canvas demos: hero workspace, chart lab (custom intervals × 15 chart types + drawings), 16-chart linked grid, Pine, strategy research, multi-symbol replay, journal, alert tree and the MCP chat. |
| `assets/og.png` | 1200 × 630 social preview image. |
| `assets/*.svg`, `apple-touch-icon.png` | Brand mark and icons. |

The language defaults to the visitor's browser (`zh*` → Chinese, otherwise English)
and remembers the 中 / EN toggle in `localStorage`.

Every chart on the page is drawn from seeded, simulated data, and the page labels it
as demo data. Nothing fetches live market data. Keep product claims in sync with the
code on `main` (exchange count from the pinned CCXT version, chart types in
`frontend/src/shared/mainChartTypes.ts`, drawing tools in
`frontend/src/features/drawings/drawingTypes.ts`, workspace limits in
`chartWorkspaceCapacity.ts`, MCP tools in `frontend/desktop/local-mcp-server.mjs`)
and update the "Current scope" list when a limit changes.

## Edit and preview

Run `python -m http.server 4173 --bind 127.0.0.1` from this folder, then open
http://127.0.0.1:4173/. To preview English, click **EN** in the header.

To refresh `assets/og.png`, capture the top of the Chinese page at 1200 × 630
(for example with headless Edge or Chrome and `--lang=zh-CN`) once the
entrance animations have finished.

## Deployment

GitHub Pages publishes from `codex/website`, root (`/`). Push a commit to that
branch to update the website. Keep `.nojekyll` and `CNAME` in place.

The custom domain is `candlescope.app`. DNS should contain these apex A records:

```
185.199.108.153
185.199.109.153
185.199.110.153
185.199.111.153
```

The `www` CNAME should point to `helenananaa.github.io`.
Enable Enforce HTTPS once GitHub has issued the certificate.
GitHub's DNS and certificate changes may take up to 24 hours to finish.
