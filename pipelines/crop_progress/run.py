"""NASS weekly crop progress and condition, with a condition-based yield model, for corn, soybeans,
winter wheat and spring wheat. Adapted, with permission, from an existing open-source pipeline.

Run by scripts/build-data.mjs. Prints one JSON object to stdout ({data, latest, n, src, note, partial});
progress messages go to stderr. Needs NASS_API_KEY.

Requests (national level only, so each stays far below Quick Stats' 50,000-row cap):
  - weekly CONDITION since 1990   (yield model and the good/excellent chart)
  - weekly PROGRESS for the last 6 years (this year vs last year vs 5-year average)
  - annual YIELD since 1988        (trend and model target) and this year's latest USDA forecast
A crop whose requests fail is skipped (partial), the others are still published.

Local test without a key: NASS_FIXTURE=<dir> reads <dir>/crop_progress/<crop>/*.csv.gz and
<dir>/annual/<crop>/*.csv.gz (the Quick Stats column layout) instead of calling the API.
"""
import gzip, csv, json, os, sys, time
from pathlib import Path

import numpy as np
import pandas as pd
import requests

KEY = os.environ.get("NASS_API_KEY", "").strip().strip("'\"")
FIXTURE = os.environ.get("NASS_FIXTURE")
API = "https://quickstats.nass.usda.gov/api/api_GET/"
UA = {"User-Agent": "grains-monitor build (+https://github.com/DrNas/grains-monitor)"}
FIRST_COND_YEAR = 1990
NOW = pd.Timestamp.now(tz="UTC").tz_localize(None)
CUR = NOW.year

# key: (Quick Stats commodity, short_desc prefix, label, final-yield short_desc, model week candidates)
CROPS = {
    "corn": ("CORN", "CORN", "Corn", "CORN, GRAIN - YIELD, MEASURED IN BU / ACRE", range(28, 37)),
    "soybeans": ("SOYBEANS", "SOYBEANS", "Soybeans", "SOYBEANS - YIELD, MEASURED IN BU / ACRE", range(30, 38)),
    "wheat": ("WHEAT", "WHEAT, WINTER", "Winter wheat", "WHEAT, WINTER - YIELD, MEASURED IN BU / ACRE", range(16, 23)),
    "spring_wheat": ("WHEAT", "WHEAT, SPRING, (EXCL DURUM)", "Spring wheat", "WHEAT, SPRING, (EXCL DURUM) - YIELD, MEASURED IN BU / ACRE", range(26, 32)),
}
W = {"VERY POOR": 1, "POOR": 2, "FAIR": 3, "GOOD": 4, "EXCELLENT": 5}


def log(*a):
    print(*a, file=sys.stderr, flush=True)


# ---------- fetching ----------
def nass(**params):
    """One Quick Stats request with retries and backoff. Returns a list of row dicts ([] when NASS has no data)."""
    last = None
    for attempt in range(4):
        if attempt:
            time.sleep(4 * 2 ** (attempt - 1))   # 4, 8, 16 s
        try:
            r = requests.get(API, params={"key": KEY, "format": "JSON", **params}, headers=UA, timeout=180)
            if r.status_code == 200:
                return r.json().get("data", [])
            t = r.text.lower()
            if r.status_code == 400 and "no data" in t:
                return []
            last = f"HTTP {r.status_code}: {r.text[:120]}"
            if r.status_code in (401, 403):
                break   # a bad key will not fix itself
        except Exception as e:   # network error, bad JSON
            last = str(e)[:160]
        log("  retry", params.get("commodity_desc"), params.get("statisticcat_desc"), last)
    raise RuntimeError(f"NASS {params.get('commodity_desc')} {params.get('statisticcat_desc')}: {last}")


_fixture_cache = {}


def fixture(commodity, kind):
    k = (commodity, kind)
    if k not in _fixture_cache:
        rows = []
        for f in sorted((Path(FIXTURE) / kind / commodity.lower()).glob("*.csv*")):
            with (gzip.open(f, "rt") if f.suffix == ".gz" else open(f)) as fh:
                rows += list(csv.DictReader(fh))
        _fixture_cache[k] = rows
    return _fixture_cache[k]


def weekly(commodity, stat, first_year):
    if FIXTURE:
        return [r for r in fixture(commodity, "crop_progress") if r["agg_level_desc"] == "NATIONAL"
                and r["statisticcat_desc"] == stat and int(r["year"]) >= first_year]
    return nass(commodity_desc=commodity, agg_level_desc="NATIONAL", statisticcat_desc=stat, source_desc="SURVEY",
                freq_desc="WEEKLY", year__GE=first_year)


def annual_yield(commodity):
    if FIXTURE:
        return [r for r in fixture(commodity, "annual") if r["agg_level_desc"] == "NATIONAL" and r["statisticcat_desc"] == "YIELD"]
    return nass(commodity_desc=commodity, agg_level_desc="NATIONAL", statisticcat_desc="YIELD", source_desc="SURVEY",
                freq_desc="ANNUAL", year__GE=1988)


def frame(rows):
    d = pd.DataFrame(rows)
    if d.empty:
        return d
    d["v"] = pd.to_numeric(d["Value"].astype(str).str.replace(",", ""), errors="coerce")
    d["year"] = d["year"].astype(int)
    if "week_ending" in d:
        d["week_ending"] = pd.to_datetime(d["week_ending"], errors="coerce")
    return d


# ---------- condition and yield model (the model logic is unchanged from the source) ----------
def condition(d, prefix):
    d = d[d.short_desc.str.startswith(prefix + " - CONDITION")].copy()
    d["cat"] = d.short_desc.str.extract(r"PCT (.+)$")[0]
    d = d[d.cat.isin(W)]
    p = d.pivot_table(index="week_ending", columns="cat", values="v", aggfunc="last").sort_index()
    p = p.dropna(subset=["GOOD", "EXCELLENT"])
    out = pd.DataFrame(index=p.index)
    out["ge"] = p.GOOD + p.EXCELLENT
    pf = p.reindex(columns=list(W)).fillna(0)
    tot = pf.sum(axis=1)
    out["idx"] = (sum(pf[c] * w for c, w in W.items()) / tot * 20).where(tot >= 95)   # 20..100; incomplete rows dropped
    out["vp_p"] = pf["VERY POOR"] + pf["POOR"]
    out["year"] = out.index.year
    out["week"] = out.index.isocalendar().week.values.astype(int)
    if "WINTER" in prefix:   # autumn ratings belong to next year's crop: week 44 -> year+1, week -8
        fall = out.week >= 35
        out.loc[fall, "year"] += 1
        out.loc[fall, "week"] -= 52
    return out


def final_yields(d, ydesc):
    d = d[(d.short_desc == ydesc) & (d.reference_period_desc == "YEAR")]
    return d.groupby("year").v.last().sort_index()


def usda_current(d, ydesc, year):
    """USDA's latest yield for `year`: the final estimate, else the newest monthly forecast."""
    d = d[(d.short_desc == ydesc) & (d.year == year)]
    if d.empty:
        return None, None
    fin = d[d.reference_period_desc == "YEAR"]
    if len(fin):
        return float(fin.v.iloc[-1]), "final"
    order = ["AUG", "SEP", "OCT", "NOV", "DEC", "JAN"]
    fc = d[d.reference_period_desc.str.contains("FORECAST", na=False)].copy()
    if fc.empty:
        return None, None
    fc["m"] = fc.reference_period_desc.map(lambda s: next((i for i, m in enumerate(order) if m in s), -1))
    r = fc.sort_values("m").iloc[-1]
    return float(r.v), r.reference_period_desc.replace("YEAR - ", "").title()


def trend(y, upto, start=1990):
    x = y[(y.index >= start) & (y.index < upto)]
    if len(x) < 8:
        return np.nan
    b, a = np.polyfit(x.index, x.values, 1)
    return a + b * upto


def model(cond, y, weeks):
    """Pick the week with the best leave-one-year-out fit among candidates; report that test."""
    best = None
    years = sorted(set(cond.year) & set(y.index))
    for wk in weeks:
        rows = []
        for yr in years:
            c = cond[(cond.year == yr) & (cond.week <= wk)].dropna(subset=["idx"])
            if c.empty or c.week.max() < wk - 1:
                continue
            t = trend(y, yr)
            if np.isnan(t):
                continue
            rows.append(dict(year=yr, idx=c.idx.iloc[-1], dev=y[yr] - t, trend=t, actual=y[yr]))
        r = pd.DataFrame(rows)
        if len(r) < 12:
            continue
        preds = []
        for i, row in r.iterrows():
            tr = r.drop(i)
            b, a = np.polyfit(tr.idx, tr.dev, 1)
            preds.append(row.trend + a + b * row.idx)
        r["pred"] = preds
        mae, mae_t = (r.pred - r.actual).abs().mean(), (r.trend - r.actual).abs().mean()
        if best is None or mae < best["mae_model"]:
            b, a = np.polyfit(r.idx, r.dev, 1)
            best = {"week": int(wk), "n": int(len(r)), "mae_model": round(float(mae), 2), "mae_trend": round(float(mae_t), 2),
                    "slope": round(float(b), 3), "intercept": round(float(a), 3),
                    "hit_direction": round(float((np.sign(r.pred - r.trend) == np.sign(r.actual - r.trend)).mean()), 2),
                    "years": r.year.tolist(), "pred": r.pred.round(1).tolist(), "actual": r.actual.round(1).tolist()}
    return best


# ---------- progress ----------
def _at(pts, x):
    """A cumulative % series (sorted [(day_of_year, pct)]) read at day x: linear between reports (NASS skipped
    reports during the Oct-Nov 2025 shutdown), held after the last one (NASS stops reporting a stage near 100%),
    0 before the first one if the season started low, else unknown."""
    if not pts:
        return None
    if x < pts[0][0]:
        return 0.0 if pts[0][1] <= 20 else None
    if x >= pts[-1][0]:
        return pts[-1][1]
    for (x0, v0), (x1, v1) in zip(pts, pts[1:]):
        if x0 <= x <= x1:
            return v0 + (v1 - v0) * (x - x0) / (x1 - x0)


def progress(d, prefix):
    """Per stage: this season, last season and the 5-year average. Past seasons are read at the same calendar
    date as this season's reports (day of year, interpolated), which is how NASS lines up its own comparisons;
    NASS's published 5-year average is not in the API. The current season is chosen per stage, because winter
    wheat planted this autumn is filed under next year's crop while its harvest belongs to this year's."""
    # corn harvest is filed as "CORN, GRAIN - PROGRESS ..." while the other corn stages are "CORN - PROGRESS ..."
    d = d[d.short_desc.str.startswith(prefix + " - PROGRESS, MEASURED IN PCT ")
          | d.short_desc.str.startswith(prefix + ", GRAIN - PROGRESS, MEASURED IN PCT ")].copy()
    if d.empty:
        return []
    d["stage"] = d.short_desc.str.extract(r"MEASURED IN PCT (.+)$")[0]
    d = d.dropna(subset=["week_ending", "v"])
    d["doy"] = d.week_ending.dt.dayofyear - d.week_ending.dt.is_leap_year.astype(int) * (d.week_ending.dt.month > 2)
    out = []
    for stage, g in d.groupby("stage"):
        if stage.startswith("PLANTED OR") or "MARKETED" in stage:
            continue
        cy = int(g.year.max())
        series = {yr: sorted(zip(h.doy.astype(int), h.v.astype(float))) for yr, h in g.groupby("year")}
        cur = series.get(cy, [])
        prev5 = [series[y] for y in range(cy - 5, cy) if y in series]
        lo, hi = int(g.doy.min()), int(g.doy.max())
        grid = list(range(lo, hi + 1, 7))

        def avg_at(x):
            vals = [v for v in (_at(p, x) for p in prev5) if v is not None]
            return round(float(np.mean(vals)), 1) if len(vals) >= 3 else None

        def ly_at(x):
            v = _at(series.get(cy - 1, []), x)
            return None if v is None else round(float(v), 1)

        last = None
        if cur:
            x, v = cur[-1]
            prev = cur[-2] if len(cur) > 1 else None
            last = {"date": g[(g.year == cy) & (g.doy == x)].week_ending.max().strftime("%Y-%m-%d"), "doy": int(x),
                    "pct": v, "chg": None if prev is None else round(v - prev[1], 1), "ly": ly_at(x), "avg5": avg_at(x)}
        ly = series.get(cy - 1, [])
        out.append({"stage": stage.title(), "year": cy, "start": int(g[g.year == cy].week_ending.min().strftime("%Y%m%d")),
                    "cur": [[int(x), v] for x, v in cur], "ly": [[int(x), v] for x, v in ly],
                    "avg5": [[x, a] for x in grid if (a := avg_at(x)) is not None], "last": last})
    out.sort(key=lambda s: s["start"])   # in the order the stages happen
    for s in out:
        del s["start"]
    return out


def crop(key):
    commodity, prefix, label, ydesc, weeks = CROPS[key]
    cond_rows = frame(weekly(commodity, "CONDITION", FIRST_COND_YEAR))
    prog_rows = frame(weekly(commodity, "PROGRESS", CUR - 6))
    yld_rows = frame(annual_yield(commodity))
    entry = {"label": label}
    latest = None
    if not cond_rows.empty:
        cond = condition(cond_rows, prefix)
        if not cond.empty:
            entry["ge"] = {str(yr): [[int(w), round(float(v), 1)] for w, v in zip(g.week, g["ge"])]
                           for yr, g in cond.groupby("year") if yr >= CUR - 10}
            # 5-year average G/E by week (previous 5 crop years)
            cy = int(cond.year.max())
            prev = cond[(cond.year >= cy - 5) & (cond.year < cy)]
            entry["ge_avg5"] = [[int(w), round(float(v), 1)] for w, v in prev.groupby("week")["ge"].mean().items()
                                if prev[prev.week == w].year.nunique() >= 3]
            cur = cond[cond.year == cy]
            L = cur.iloc[-1]
            ly = cond[(cond.year == cy - 1) & ((cond.week - L["week"]).abs() <= 1)]   # same week, give or take one
            entry["cond_last"] = {"year": cy, "week": int(L["week"]), "date": cur.index[-1].strftime("%Y-%m-%d"),
                                  "ge": round(float(L["ge"]), 1), "vp_p": round(float(L["vp_p"]), 1),
                                  "chg": round(float(L["ge"] - cur.iloc[-2]["ge"]), 1) if len(cur) > 1 else None,
                                  "ly": round(float(ly["ge"].iloc[-1]), 1) if len(ly) else None,
                                  "avg5": next((v for w, v in entry["ge_avg5"] if abs(w - int(L["week"])) <= 1), None)}
            latest = entry["cond_last"]["date"]
            y = final_yields(yld_rows, ydesc) if not yld_rows.empty else pd.Series(dtype=float)
            if len(y) > 10:
                m = model(cond, y, weeks)
                if m:
                    c = cur[cur.week <= m["week"]].dropna(subset=["idx"])
                    t = trend(y, cy)
                    est = t + m["intercept"] + m["slope"] * c.idx.iloc[-1] if len(c) else None
                    usda, usda_ref = usda_current(yld_rows, ydesc, cy)
                    entry["model"] = {"year": cy, "week": m["week"], "estimate": None if est is None else round(float(est), 1),
                                      "trend": round(float(t), 1), "usda": usda, "usda_ref": usda_ref,
                                      "test": {k: m[k] for k in ("n", "mae_model", "mae_trend", "hit_direction", "slope")},
                                      "history": {k: m[k] for k in ("years", "pred", "actual")}}
    if not prog_rows.empty:
        entry["progress"] = progress(prog_rows, prefix)
        dates = [s["last"]["date"] for s in entry["progress"] if s["last"]]
        if dates:
            latest = max(filter(None, [latest, max(dates)]))
    return entry, latest


def main():
    if not KEY and not FIXTURE:
        raise SystemExit("NASS_API_KEY is not set")
    data, errors, latest = {}, [], []
    for key in CROPS:
        try:
            entry, last = crop(key)
            if "ge" not in entry and "progress" not in entry:
                raise RuntimeError("no rows")
            data[key] = entry
            if last:
                latest.append(last)
            log(key, "ok", last)
        except Exception as e:
            errors.append(f"{key} ({str(e)[:80]})")
            log(key, "FAILED", e)
    if not data:
        raise SystemExit("every crop failed: " + "; ".join(errors))
    print(json.dumps({"data": {"crops": data}, "latest": max(latest) if latest else None, "n": len(data),
                      "src": "USDA NASS Quick Stats (Crop Progress, Crop Production)",
                      "note": ("missing: " + ", ".join(errors)) if errors else "", "partial": bool(errors)},
                     separators=(",", ":"), allow_nan=False, default=lambda o: None))


if __name__ == "__main__":
    main()
