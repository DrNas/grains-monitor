# Staging site (test copy, not published)

A second copy of the site for trying changes before they reach the live one. It is separate from the main site:

| | Main site | Staging site |
|---|---|---|
| Built by | `.github/workflows/build.yml` (from `main`, on a schedule) | `.github/workflows/staging.yml` (from the work branch, on every push or "Run workflow") |
| Code | `main` | the work branch (`claude/quirky-wright-omj7zm`) |
| Data history | read from the published site | its own, kept in GitHub's build cache (`staging-site-…`); never reads or writes the main site's |
| On the web | yes (GitHub Pages) | no: saved as a download on the run page |

## Looking at it

1. GitHub → **Actions** → **Staging build (not published)** → the latest run.
2. Under **Artifacts**, download `staging-preview`, unzip it and double-click `index.html`. That's it.

`staging-preview` is the same site rearranged to open from files (`scripts/make-preview.mjs`). `staging-site` is the
site exactly as it would be hosted; to look at that one, unzip it and start a small local web server in the folder:

```bash
python -m http.server 8000
```

Then open http://localhost:8000/ in a browser.

The download is kept for 14 days. To rebuild now: **Run workflow** on the same Actions page.

## Giving it a domain later

1. Pick where to host it (a second GitHub Pages repo, Cloudflare Pages, Netlify; all have free tiers).
2. In `staging.yml`, set `SITE_URLS` to the new address (used for links and offline copies) and add a deploy step for that host.
3. Point the domain's DNS at the host.

Nothing on the main site changes in any of these steps.
