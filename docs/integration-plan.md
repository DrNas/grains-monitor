# Integration plan: adapted data pipelines (Step 1 audit)

Status: **approved 2026-11-10, building.** The owner chose: build in the existing `build.yml` (no data commits), multi-page desks with a shared stylesheet, Groq tab skipped, dark only.

## Build log
| Step | What | Where | Checked |
|---|---|---|---|
| 1 | Shared stylesheet (tokens + base, colors unchanged), desk script (header, data loading, card with source/latest footer, table, tiles, chart wrapper with crosshair and PNG export), desk nav on Home, credits line, `.env.example`, Python support in the build, `check-pipelines.yml` | `assets/`, `index.html`, `scripts/build-data.mjs`, `.github/workflows/` | Home renders pixel-identical apart from the new nav links |
| 2 | Crop progress & condition + yield model | `pipelines/crop_progress/`, `grains/` | Run on 41 years of archived NASS data; 5-yr averages match NASS's published ones (corn harvest 86%, soybeans 91% on Nov 8, 2026); live-key run passed (check run 42854116404, 36 s, all four crops; winter wheat picks up this autumn's planting, which the source pipeline missed) |
| 3 | WASDE balance sheets: U.S. balance with this month's changes, revision path per line, first-vs-final revision stats, key countries, stocks-to-use vs farm price | `pipelines/wasde/`, `data/wasde/history.csv.gz` (USDA WASDE Apr 2010–Oct 2026, grains tables only, 2.2 MB; later months fetched from usda.gov at build time), `grains/` | Current figures match the source desk; usda.gov refused this sandbox's request for the Nov 2026 file (HTTP 403) and the source degrades to PARTIAL with a note. Live-key run (check run 42866015141): usda.gov refuses GitHub's runners too (HTTP 403), so the Nov 2026 release is missing until a decision is made (see Known issues) |
| 4 | Export sales (commitments vs USDA, implied exports, backtest, weekly net sales, top buyers, wheat by class) + export inspections pace | `pipelines/export_sales/`, `grains/` | Every current-week figure matches the source desk's output exactly for corn, soybeans, meal, oil and wheat; inspections within 0.3 pts (actual WASDE release dates instead of the 12th). History is cached between runs in `data/export_sales.cache.json`. Live-key run passed: FAS works with `DATAGOV_API_KEY`, FGIS downloads from GitHub, first run 4.5 min (history), identical figures |
| 5 | Energy fundamentals: signal scorecard; gas storage vs 5-yr range, weekly change, surplus/deficit, regions, season-end projection, monthly balance, STEO, Henry Hub; crude and Cushing stocks, builds/draws, refining, crude balance, WTI/Brent; distillate and gasoline stocks, demand, Gulf Coast cracks and their seasonality; inventory fair values | `pipelines/energy/` (48 EIA series), `energy/` | Distillate and gasoline fair values match the source exactly. EIA stopped publishing NYMEX futures in April 2024 (the source's EIA futures series end 2024-04-05), so gas is valued on Henry Hub spot (R² 0.65 vs 0.68 on futures in the source) and the WTI spread model waits for the prices pipeline; a guard drops any model whose price series has stopped. Live-key run passed (check run 42867036185, all four markets to Oct 30, 2026) |
| 6 | Positioning (no-price parts): desk brief (copy as text), setups and risk flags, positioning monitor with setup score and desk read, sectors, commercials-vs-funds scatter, 26-week percentile heatmap, index traders (CIT) by market and breadth, market detail (net by trader group, trader counts, seasonality, CIT vs funds); look-back and crop-year selectors | `pipelines/positioning/` (CFTC COT for 21 BCOM markets since 2006 + CIT for 13 ag markets), `positioning/` (with the source's analysis engine `insights.js`) | Snapshot identical to the source's for every market (levels, changes, z, COT index, streak, percentiles), CIT aggregate and heatmap identical; live CFTC fetch identical to the archive. Full fetch 2.5 min, so a run first checks the CFTC's latest report date and republishes the previous build when nothing is new (9 s). Trade ideas, trigger levels and dollar exposure wait for the prices pipeline. Live run passed (check run 42895193088; energy now OK too) |
| 7 | Macro: written read; fed funds (effective and target), SOFR, Treasury par curve vs 1w/1m/1y, yield history, 2s10s, real yields and breakevens; Treasury General Account, bills outstanding, weekly bill issuance net of maturities (new); BLS/BEA economy table | `pipelines/macro/`, `macro/` | Live run passed (check run 42900015918): every source answered with the build's honest user agent, including Treasury; UMich left out as stale (its free mirror stopped updating). SOFR/fed funds futures path waits for the prices pipeline; the commercial economic-calendar feed the source used is not carried over |
| — | Page check in `check-pipelines.yml` (`scripts/check-pages.mjs`): every page opened with the run's data at desktop and phone width; fails on script errors; screenshots kept as an artifact | `scripts/`, `.github/workflows/` | Check run 42900617045: all charts drew on every page (home 18/18, positioning 6/6, grains 9/9, energy 6/6, macro 7/7), no script errors, no sideways scroll |
| 8 | Prices (Yahoo, honest user agent, spaced requests with backoff): front-month history since 2006 for the 21 positioning markets plus S&P 500 and VIX (cached; 3-month top-up), tradable front contract, carry, risk regime, WTI and gas curves, fed funds and SOFR futures strips. Unlocks: positioning trade ideas, watchlist, scorecard, trigger levels, dollar exposure, Px 4w; energy futures curves; macro policy path. Positioning now recomputes with fresh prices every build: with no new CFTC report it rebuilds the COT history from the previous build's files and fetches CIT fresh (identical output, 45 s) | `pipelines/prices/`, `pipelines/positioning/`, `positioning/`, `energy/`, `macro/` | Check run 42906305849: prices OK for all 21 markets, curves and rate strips; every page drew all charts (positioning 6/6 with 7 tables, energy 7/7, macro 8/8), no script errors. TradingView not added: the only client forges TradingView's own web-app origin, which is against its terms; the WTI 1st-2nd spread model still needs a 2nd-month history the free feed does not have |
| 9 | Home "What changed this week": fund buying/selling with flow σ, crowded markets, largest price moves, WASDE ending-stock revisions, in-season crop progress vs 5-yr, export commitments vs USDA, energy inventories vs 5-yr, rates, futures-implied policy rate, TGA | `assets/changes.js`, `index.html` | Rendered locally on real desk data, no errors |
| 10 | Backtests: the source's weekly backtest lab (trend, COT, COT×trend, fundamentals, seasonal, combined; 10% vol, 5 bp costs, Friday-release timing, in/out of sample, recent-regime windows, noise bar) on 21 markets; carry rules left out (no carry history) | `pipelines/backtests/`, `backtests/` | Local run on real prices and the live CFTC history: 564 tests, noise bar Sharpe 0.80, 14 s; page renders with no errors |

Agreed scope (2026-11-10): Positioning, Grains & oilseeds, Livestock (beef and pork), Energy, Backtests, Markets & macro.
Out for now: dairy, cotton, sugar, coffee, equities, the softs options vol desk (it only covers cotton, coffee and sugar), vendor-discovery, and the email reports (all of them are cotton reports).
Prices: Yahoo (we already use it in `scripts/sources/cot.mjs`) plus TradingView settlements.

## 1. Our site today

| | |
|---|---|
| Framework | None: one static `index.html` (~61 KB), vanilla JS |
| Routing | Single page, anchor links (`#recap`, `#cal`, `#cot`, `#meat`, `#basis`, `#wx`, `#drought`) |
| Theme | CSS variables on `:root` in `index.html`, **dark only**. A few hex values are hard-coded in rules (`#21262d`, `#1f6feb`, `#11161d`…) |
| Charts | Chart.js 4.4.1 from cdnjs |
| Data | `scripts/build-data.mjs` (Node) runs `scripts/sources/*.mjs` and writes `_site/data/latest.json`; the page reads only that file |
| Hosting | GitHub Pages via Actions (`.github/workflows/build.yml`), custom domain grains.manasbafna.com |
| Nav | 7 anchor links in a sticky header |

## 2. Features in his repos (in scope)

The umbrella repo (`US-commodity-desk`) holds copies of most of the others. Each feature gets ported from one copy only.

| Section | Feature (his tab) | His code | Source | Updates | Secret | Ours |
|---|---|---|---|---|---|---|
| Positioning | Summary & ideas: desk brief, trade ideas, positioning monitor | cftc-cot-full | CFTC COT + prices | Weekly (Fri) | none | Missing |
| | COT analyzer | cftc-cot-full | CFTC COT | Weekly | none | **Partial** (we have MM net, 3y/5y percentiles from 2006) |
| | Index (CIT) | cftc-cot-full `fetch_cit_data.py` | CFTC Supplemental | Weekly | none | Missing |
| | Triggers & flows (breakout levels, 26-week heatmap) | cftc-cot-full | COT + prices | Weekly | none | Missing |
| | Scatter, seasonality, custom formula | cftc-cot-full | COT + prices | Weekly | none | Missing |
| | AI analysis | cftc-cot-full | Groq | On demand | GROQ_API_KEY | Missing (optional) |
| Grains | Crop progress & condition (corn, soy, wheat, sorghum) | `pipelines/crop_progress.py` | NASS Quick Stats | Weekly (Mon) | NASS_API_KEY | Missing (on our roadmap) |
| | Export sales + FGIS inspections | `pipelines/grains_trade.py`, `models/grains_sales.py` | FAS ESR, FGIS | Weekly (Thu 8:30) | FAS_API_KEY | Missing (on our roadmap) |
| | WASDE balance sheets + brief | `models/grains_wasde*.py` | USDA WASDE | Monthly | none | **Partial** (dates only, in the calendar) |
| | Global S&D / geo (PSD, Comtrade) | `pipelines/geo.py` | FAS PSD, UN Comtrade, NASS, USDM | Weekly | NASS_API_KEY | Missing |
| | South America (Brazil, Argentina) | `pipelines/south_america.py` | Comex Stat, CONAB, MAGyP, FAS | Weekly | FAS_API_KEY | Missing |
| | Grains desk: primer, S&D → price, options, outlook, seasonality | `models/grains_*.py` | mixed | Daily/weekly | NASS, FAS | Missing |
| | Basis, barge rates | `pipelines/agtransport_basis.py` | AgTransport | Weekly | none | **Partial** (we have MMN basis; barge rates are on our roadmap) |
| | Weather ensemble | `pipelines/wx_ensemble.py` | Open-Meteo | 2× daily | none | **Partial** (we have 16-day forecast vs normal) |
| | Drought | `pipelines/geo.py usdm` | USDM | Weekly | none | **Have** |
| Livestock | Hogs and cattle S&D, convergence, expiry | `models/hogs*.py`, `models/cattle*.py`, `pipelines/usda_livestock.py` | NASS, ERS, AMS | Daily/weekly | NASS, AMS | **Partial** (we have the cash/slaughter side) |
| Energy | Gas storage, S&D, gas-weighted degree days, weather storage model, fair value | natgas, `models/energy_*.py` | EIA v2, Open-Meteo | Weekly (Thu) / daily | EIA_API_KEY | Missing |
| | Crude & products stocks, refining, cracks, curves | natgas, `pipelines/energy_eia.py`, `energy_prices.py` | EIA v2, Yahoo | Weekly (Wed) / daily | EIA_API_KEY | Missing |
| | Signal scorecard, positioning matrix | natgas | EIA, CFTC, prices | Daily | EIA_API_KEY | Missing |
| Backtests | Baskets, single-market rules, technical patterns, regime check | `models/backtest_lab.py`, `basket_lab.py`, `cot_backtest.py`, `tech_lab.py` | prices + COT + fundamentals | Weekly (Sat) | none | Missing |
| Macro | Futures/FX/rates snapshot, economic calendar | `pipelines/markets.py`, `econ_calendar.py` | Yahoo, faireconomy | Hourly | none | Missing |
| | Rates & liquidity (SOFR, TGA, T-bills, BLS) | `pipelines/us_macro.py`, `models/macro.py` | NY Fed, Treasury, BLS, DBnomics | Daily | none | Missing (partly covers the Step 3 "rates & macro" idea) |
| | Options pricer (Black-76) | US-commodity-desk | calculator | — | none | Missing |

Not carried over, besides the excluded sections: his `news.py` (Google News scraping), the Cloudflare chat proxy and the desk login (his private setup), and the China, India, Europe and palm pipelines (cotton and palm).

## 3. Secrets (names only)

| His secret | Needed for | Ours |
|---|---|---|
| NASS_API_KEY | crop progress, geo, livestock | **Set** (stored, not used yet) |
| AMS_API_KEY | livestock | **Set** as `MMN_API_KEY` (same MyMarketNews key). Pipelines read `MMN_API_KEY` |
| FAS_API_KEY | export sales, South America | **Set** as `DATAGOV_API_KEY` (api.data.gov). Pipelines read `DATAGOV_API_KEY` |
| EIA_API_KEY | energy | **Set** (stored, not used yet) |
| USDA_API_KEY | only his probe script | Not needed |
| GROQ_API_KEY | AI analysis (optional) | **Missing**. Free at console.groq.com, only if that tab is wanted |
| SMTP_*, EMAIL_FROM/TO | cotton emails | Not needed (out of scope) |
| CLOUDFLARE_*, DASHBOARD_PASSWORD, DESK_USERS | his private setup | Dropped |

Confirmed by the owner on 2026-11-10: the repo has exactly MMN_API_KEY, NASS_API_KEY, DATAGOV_API_KEY and EIA_API_KEY. No new secrets are needed for the agreed scope. There are no `.env*` files in the repo; a `.env.example` (names only) will be added. This session has no keys, so real-data checks run in GitHub Actions.

## 4. Proposed structure

**Pages.** `index.html` is already 61 KB, so the new desks become separate static pages that share one header, one stylesheet and one components script. Today's `index.html` stays as it is (nothing removed).

```
/                  Home (today's page: recap, calendar, positioning, livestock, basis, weather, drought) + "what changed this week"
/positioning/      COT desk brief & ideas, monitor, analyzer, CIT, triggers & flows, scatter, seasonality
/grains/           crop progress, export sales, WASDE, global S&D, South America, barge/basis, grains desk
/livestock/        hogs & cattle S&D, convergence (today's livestock section stays on Home and is linked)
/energy/           gas storage, S&D, weather model, fair value, oil stocks, refining & cracks, scorecard
/backtests/        backtest results
/macro/            markets snapshot, rates & liquidity, econ calendar, options pricer
```

Nav: Home · Positioning · Grains · Livestock · Energy · Backtests · Macro, plus search across desks.

**Shared components** (`assets/site.css`, `assets/components.js`):
- Chart wrapper: Chart.js with theme tokens, crosshair, latest-point label, PNG export, and a source + last-updated footer
- Data table: sortable, sticky header, number formatting, mobile scroll
- Last-updated badge: OK/PARTIAL/CACHED/FAILED, the same states as `latest.json` today
- Signal scorecard tile: percentile, regime, change

Moving the `:root` tokens into `assets/site.css` and replacing the hard-coded hex values counts as **changing global styles. Approval needed.** Colors stay exactly the same.

**Data flow.**
```
.github/workflows/<feature>.yml (staggered cron, concurrency group)
  → pipelines/<feature>/*.py  (his Python, keys from secrets, retries/backoff, a failed source skips its dataset)
  → data/<feature>/*.json committed to main
  → existing build.yml runs on the data push and deploys Pages
  → /<desk>/ page reads data/<feature>/*.json
```
About 35 relevant workflows of his get consolidated into roughly 8: positioning (Fri), grains-weekly (Mon NASS, Thu FAS), wasde (monthly), energy (Wed/Thu + daily), macro (daily), prices (daily, Yahoo + TradingView), livestock-extra (daily), backtests (Sat).

## 5. Build order (easiest and highest value first)

1. **Scaffolding:** shared CSS/JS, the multi-page shell with nav, `.env.example`, the credits line. Then a check that today's page looks unchanged.
2. **Crop progress & condition** (NASS; small; on our roadmap)
3. **Export sales + inspections** (FAS; on our roadmap)
4. **Energy, fundamentals only:** gas storage, oil and product stocks, refining (EIA, no prices needed)
5. **Positioning, no-price parts:** CIT, positioning monitor, scatter, seasonality, desk brief
6. **WASDE balance sheets + brief** (grains)
7. **Macro:** rates & liquidity (keyless), econ calendar
8. **Prices pipeline** (Yahoo + TradingView). This unlocks trade ideas, triggers, technicals, energy curves and fair value, and the markets snapshot.
9. **Livestock S&D, South America, global S&D, barge rates**
10. **Backtests**
11. **Home "what changed this week"**, mobile pass, Step 3 extras

Each step: pipeline, then workflow, then page, then a grep for "BMR-Com"/"malli"/"bmr-com.github.io", then a check with real data, then a commit.

## 6. Open questions

1. Approve the multi-page structure and moving the CSS tokens into a shared file (colors unchanged)?
2. TradingView isn't an official API: it's an unofficial feed that may break, and its terms don't allow scraping. Proceeding as you asked; prices fall back to Yahoo when TradingView fails.
3. Include the Groq "AI analysis" tab (needs a free Groq key), or leave it out?
4. Dark mode only, like today's site?

## Known issues
- **WASDE November 2026 and later**: usda.gov answers HTTP 403 to automated requests (from this sandbox and from GitHub's runners). The source desk got round it by impersonating a Chrome browser; that is a decision for the owner. Until then the WASDE balance sheets and the export pace show the last release in `data/wasde/history.csv.gz` (October 2026) with a PARTIAL note. Options: allow a browser user agent for usda.gov (as `calendar.mjs` already does for NASS and CFTC), try USDA's ESMIS archive as a second source, or add each month's CSV to the history file by hand.
- **NYMEX futures**: EIA stopped publishing them in April 2024. Gas fair value uses Henry Hub spot. Prices now come from Yahoo (step 8), which gives today's curves but not a 2nd-month history, so the WTI 1st-2nd spread model is still not run.
- **TradingView**: not used. The only available client presents itself to TradingView as TradingView's own web app (forged Origin header), which is against its terms and was not built.
- **NASS shutdown gap**: no Crop Progress reports from Oct 1 to Nov 12, 2025; last season's values in that window are interpolated (noted on the page).
- **Check runs** have no published cache to start from until the branch is merged, so each one downloads the export sales history again (about 4.5 minutes).
