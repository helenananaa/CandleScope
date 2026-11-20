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

Cloudflare Workers Static Assets hosts the website in the `candlescope` Worker.
Workers Builds watches this repository's `codex/website` production branch, with
root directory `/`. Push a commit to that branch to publish a website update.
Preview builds for other branches are disabled.

Build command (copies only public website files):

```sh
mkdir -p dist && cp index.html style.css robots.txt sitemap.xml dist/ && cp -R assets dist/
```

Deploy command:

```sh
npx wrangler@4 deploy --name candlescope --assets ./dist --compatibility-date 2026-11-21
```

The temporary deployment URL is
https://candlescope.ryan-liang-work-d75.workers.dev/. Production uses
`candlescope.app` and `www.candlescope.app` as Worker custom domains with
Cloudflare-managed DNS and HTTPS. The domain registration and renewals remain
at Name.com. Cloudflare nameservers are `eleanor.ns.cloudflare.com` and
`zac.ns.cloudflare.com`. Do not restore the old GitHub Pages A records when
updating the production site.

The existing `.nojekyll` and `CNAME` files are retained for rollback during the
migration; they are not included in the Cloudflare asset upload. The previous
GitHub Pages source was `codex/website`, root `/`, with four apex A records
(`185.199.108.153`, `185.199.109.153`, `185.199.110.153`, `185.199.111.153`)
and a `www` CNAME pointing to `helenananaa.github.io`.
