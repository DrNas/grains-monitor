# Grains & Livestock Monitor: handoff

## What this is
`index.html` is a single self-contained page (Chart.js 4.4.1 from cdnjs, no framework). It reads one file, `data/latest.json`, built by `scripts/build-data.mjs` on GitHub Actions and published with the page to GitHub Pages. Unlike the funding monitor, the page never calls a data source itself: the API keys stay in repository secrets and never reach the browser. Opened as a local file, the page reads the published snapshot.

## Build
- `.github/workflows/build.yml`: weekdays at ~7:17am, 12:23pm, 3:52pm, 5:37pm and 9:13pm ET, weekends once; also on "Run workflow" and on pushes that touch the page, scripts or data.
- `scripts/build-data.mjs` runs each module in `scripts/sources/` (`load({now, keys})` → `{data, latest, n, src, note, partial}`) and writes `_site/data/latest.json` = `{generated, failed, series: {id: {label, state, latest, n, src, note, built, data}}}`.
- States: OK, PARTIAL (some sub-feeds missing, see note), CACHED (today's fetch failed; the previous published copy is kept), FAILED (failed and no previous copy). Any CACHED/FAILED ends the run red so GitHub emails the owner.
- The previous snapshot is read from `https://grains.manasbafna.com/data/latest.json`, falling back to the github.io address (`PAGES_URL` overrides).
- `scripts/lib.mjs`: HTTP with timeout/retries. `USE_CURL=1` sends requests through curl (for a sandbox whose proxy Node's fetch can't use). Local run: `USE_CURL=1 MMN_API_KEY=… node scripts/build-data.mjs`; `ONLY=cot,weather` runs a subset (the rest is copied from the published snapshot).

## Sources
| id | what | source | key |
|---|---|---|---|
| calendar | releases for the next ~3 months | NASS calendar page scraped month by month (`reports_by_date.php?view=c`), WASDE dates from `data/calendar-manual.json`, CFTC's published COT schedule (scraped), rule-based EIA (Wed 10:30) and FAS export sales (Thu 8:30), shifted a day in holiday weeks and marked "date estimated" | none |
| cot | managed money, commercial, swap, OI; 1/4-week changes, 3y/5y percentiles, run length, 6 years of weekly history | CFTC Socrata `72hh-3qpy` (disaggregated, futures only) | none |
| slaughter | daily estimated FI cattle and hog slaughter; Sun–Sat weekly totals vs year ago | MyMarketNews report 3208, section "Report Livestock Commodity" | MMN |
| basis | 17 state/port grain bid reports: rows by region and delivery point, state summaries (country elevators) | MyMarketNews "Report Detail" sections; ids in `basis.mjs` | MMN |
| livestock | 5-area weekly and daily negotiated steers (live FOB, dressed delivered), Choice/Select cutout, pork cutout and primals, national negotiated hogs, calculated Lean Hog Index; ~14 months daily history | USDA LMR datamart `mpr.datamart.ams.usda.gov/services/v1.1/reports/<id>/<section>` (2477, 2466, 2453, 2498, 2511); `q=field=value;...` filters rows | none |
| recap | video summaries from `data/recaps/*.json` (newest 10) | written by the scheduled summary task; prompt in `docs/video-summary-task.md` | none |
| weather | 9 regions (`scripts/regions.mjs`), last 30 + next 16 days, vs normals | Open-Meteo forecast API, one multi-location request | none |
| drought | U.S. and 14 states, D0–D4 cumulative %, 1/4/52-week changes | usdmdataservices.unl.edu (state `aoi` = 2-digit FIPS) | none |
| enso | ONI history, alert status and synopsis | CPC `oni.ascii.txt` and `ensodisc.shtml` | none |

The NOAA outlook maps and the Drought Monitor map are hot-linked images (always the latest).

## Details worth knowing
- **nass.usda.gov and cftc.gov** reject non-browser user agents (Azure/Akamai firewalls), so `calendar.mjs` sends a browser UA for those two. If the NASS calendar starts failing, check that first.
- **WASDE dates** are not in any feed: add each year to `data/calendar-manual.json` when USDA posts them (the calendar note warns 60 days ahead). 2026 is in; 2027 was not published as of Nov 3, 2026.
- **Basis**: "current = No" rows are forward bids and are skipped. A state's basis is averaged only across rows quoted against the same futures month (the month most rows use), because regions roll contracts on different days; the page shows "(n/m)" when not all regions use it. Weekly change compares to the report ≥6 days earlier, same region and month only.
- **Slaughter**: each daily report restates the previous days; the newest report wins for each date. The year-ago figure is per day, so week-to-date vs last year sums this week's days.
- **COT percentiles** are percentile ranks of the managed-money net within the last 3/5 years of weekly reports (ties count half).
- **Weather normals** (`data/weather-normals.json`) are day-of-year averages of 2010–2024 Open-Meteo ERA5 data, ±15-day smoothed, per region (mean of its points). They are built once by `node scripts/build-normals.mjs` (resumable: Open-Meteo's free tier counts a long-history request as hundreds of calls; downloads are cached in `.normals-cache/`, which is git-ignored). Rebuild if you add or move a point in `regions.mjs`.
- The forecast is Open-Meteo's best-match blend; days 8–16 are low-skill and labelled as such.

- **Lean Hog Index** is calculated, not CME's file: 2-day head-weighted average of LM_HG201 producer-sold negotiated, negotiated formula and swine/pork market formula net prices (keyed by slaughter date). USDA often withholds the negotiated-formula price (confidentiality); the index then uses the other two, so it can differ slightly from CME's.
- **Packer margin** shown on the page is the trader spread, cutout − cash, $/cwt carcass: pork = LM_PK602 pork cutout − LM_HG201 national negotiated net price for the same slaughter day (`margins.porkSpread`); beef = Choice cutout averaged over the week the cattle traded − LM_CT150 5-area dressed steer price (`margins.beefSpread`). `margins.beef`/`margins.pork` still hold a gross version (adds the by-product drop from MyMarketNews 2829/2835, uses the all-purchase-types hog price, $/head) that the page does not show.
- **Planned slaughter**: hogs from LM_HG201 "14-Day Scheduled Swine" (head by delivery date; next-7-day total compared with the reports a week and ~a year earlier); cattle from LM_CT106 (2656) daily committed and delivered (USDA's own week/year-ago figures).
- **Daily recap** "At a glance" is computed in the browser from the snapshot (no AI). The video recap comes from the scheduled task "Grain Markets daily video summary", which runs on the owner's computer (MON-5V4PG04) and pushes `data/recaps/<date>.json`; changing its prompt needs the owner's approval on that computer.

## Next (agreed scope not built yet)
1. **Feeder cattle index** (CME's index is built from AMS auction, direct and video reports in 12 states; not done).
2. **Grain fundamentals**: FAS export sales vs USDA's needed pace (`DATAGOV_API_KEY`), NASS crop progress/conditions vs 5-year average (`NASS_API_KEY`), EIA weekly ethanol (`EIA_API_KEY`), AgTransport barge rates.
3. **Report-day reactions**: how much each market typically moved on past report days (needs a daily futures settlement history).
