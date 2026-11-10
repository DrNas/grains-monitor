# Integration plan: adapted data pipelines (Step 1 audit)

Status: **waiting for approval.** Nothing below has been built yet.

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
| NASS_API_KEY | crop progress, geo, livestock | In `build.yml`. Check that it's set in repo secrets |
| AMS_API_KEY | livestock | Same key as our `MMN_API_KEY` (MyMarketNews). Reuse it, no new secret |
| FAS_API_KEY | export sales, South America | FAS's API uses an api.data.gov key, so our `DATAGOV_API_KEY` should work. Verify on the first run |
| EIA_API_KEY | energy | In `build.yml`. Check that it's set in repo secrets |
| USDA_API_KEY | only his probe script | Not needed |
| GROQ_API_KEY | AI analysis (optional) | **Missing** |
| SMTP_*, EMAIL_FROM/TO | cotton emails | Not needed (out of scope) |
| CLOUDFLARE_*, DASHBOARD_PASSWORD, DESK_USERS | his private setup | Dropped |

I couldn't run `gh secret list` from this session, and no keys are set in this environment, so the "set" status needs checking under Settings → Secrets and variables → Actions. There are no `.env*` files in the repo. A `.env.example` (names only) will be added.

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
