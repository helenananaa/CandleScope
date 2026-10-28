# CandleScope website

Static introduction page for https://candlescope.app/, linking visitors to
https://github.com/helenananaa/CandleScope.

This independent `codex/website` branch contains only the public website. Product
source code remains on `main`. No build tool, dependencies, or backend is required.

## Edit and preview

Edit `index.html` for content and links, and `style.css` for presentation.
Brand assets are in `assets/`; the chart is an explicitly labeled illustration,
not a product screenshot or live data. Run `python -m http.server 4173 --bind 127.0.0.1`
from this folder, then open http://127.0.0.1:4173/.

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
