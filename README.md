# Grains & Livestock Monitor

A dashboard for grain and livestock futures traders: fund positioning (CFTC COT), a USDA/CFTC/EIA report calendar with countdowns, federally inspected slaughter, cash grain basis by state, crop and feedlot weather against normal, NOAA outlooks, the Drought Monitor and ENSO. No live prices: it covers the fundamentals around them.

**Live page:** https://grains.manasbafna.com/ (also https://drnas.github.io/grains-monitor/)

A GitHub Action (`.github/workflows/build.yml`) rebuilds the data several times a day and publishes it with the page. Nothing is estimated or filled in: a missing number shows as —.

## One-time setup
1. **Settings → Pages → Build and deployment → Source: GitHub Actions.**
2. **Settings → Secrets and variables → Actions:** `MMN_API_KEY` (USDA MyMarketNews), `NASS_API_KEY`, `DATAGOV_API_KEY`, `EIA_API_KEY`. Only `MMN_API_KEY` is used today; the others are for the grain fundamentals section.
3. **Custom domain:** a DNS `CNAME` record `grains` → `drnas.github.io`, then enter `grains.manasbafna.com` under Settings → Pages → Custom domain.
4. **Actions → Build and publish → Run workflow** for the first build (later runs happen on their own).

If a source fails, the previous copy is kept and the run ends red, so GitHub emails you. The run's summary page lists every source and its status.

See `HANDOFF.md` for how everything works.
