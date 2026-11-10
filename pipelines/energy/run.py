"""Energy desk: natural gas storage and supply/demand, crude and product inventories, refining, cracks and
EIA prices, with inventory-based fair values. Adapted, with permission, from an existing open-source pipeline.

EIA Open Data v2 (key EIA_API_KEY): the 58 series in eia_series.json. Each is looked up by its EIA ID on the
listed routes; if EIA has moved it, the route's series list is searched by name (must / prefer / not patterns).
Prices are EIA's own spot prices (Henry Hub, WTI, Brent, Gulf Coast ULSD and gasoline). EIA stopped publishing
NYMEX futures settlements in April 2024, so the futures-based parts of the source model (gas front month, WTI
1st-2nd spread, forward curves) wait for the desk's futures price pipeline; until then natural gas is valued on
the Henry Hub spot price and the crude spread model is left out.

Fair values (the source model): rolling 5-year OLS of
  natural gas: log(Henry Hub spot; the source uses the front-month future) ~ storage vs 5-yr average (%) + season
  crude:       WTI 1st-2nd month spread ~ Cushing and U.S. crude stocks vs 5-yr (needs futures prices: not run yet)
  products:    Gulf Coast crack vs WTI ~ days of supply vs 5-yr + season
with a walk-forward check of whether the gap has closed over the next 4 weeks.

Run by scripts/build-data.mjs; prints {data, latest, n, src, note, partial} as JSON on stdout.
Local test without a key: ENERGY_FIXTURE=<dir> reads <dir>/<k>.json ({"rows": [[date, value], ...]}).
"""
import json, math, os, re, sys, time
from pathlib import Path

import numpy as np
import pandas as pd
import requests

KEY = os.environ.get("EIA_API_KEY", "").strip().strip("'\"")
FIXTURE = os.environ.get("ENERGY_FIXTURE")
SPECS = json.loads((Path(__file__).resolve().parent / "eia_series.json").read_text())
API = "https://api.eia.gov/v2"
NOW = pd.Timestamp.now(tz="UTC").tz_localize(None)
FACETS = {}


def log(*a):
    print(*a, file=sys.stderr, flush=True)


# ---------------- fetching ----------------
def get(url, params):
    last = None
    for attempt in range(4):
        if attempt:
            time.sleep(4 * 2 ** (attempt - 1))
        try:
            r = requests.get(url, params={"api_key": KEY, **params}, timeout=90)
            if r.status_code == 200:
                return r.json()
            last = f"HTTP {r.status_code}"
            if r.status_code in (400, 401, 403, 404):
                break
        except Exception as e:
            last = str(e)[:120]
    if last and last.startswith("HTTP 40") and last != "HTTP 404" and last != "HTTP 400":
        raise RuntimeError(f"EIA refused the request ({last}): check EIA_API_KEY")
    return None


def rows_for(route, sid, freq):
    q = {"frequency": freq, "data[0]": "value", f"facets[{'seriesId' if route == 'steo' else 'series'}][]": sid,
         "sort[0][column]": "period", "sort[0][direction]": "desc", "offset": 0, "length": 5000}
    j = get(f"{API}/{route}/data/", q)
    out = []
    for r in ((j or {}).get("response") or {}).get("data") or []:
        try:
            out.append([str(r["period"])[:10], float(r["value"])])
        except (TypeError, ValueError, KeyError):
            continue
    return sorted(out)


def facets(route):
    if route not in FACETS:
        j = get(f"{API}/{route}/facet/{'seriesId' if route == 'steo' else 'series'}/", {})
        FACETS[route] = [{"id": x.get("id"), "name": x.get("name") or ""} for x in ((j or {}).get("response") or {}).get("facets", [])]
    return FACETS[route]


def score(f, sp):
    s = f["name"] + " " + f["id"]
    if not all(re.search(p, s, re.I) for p in sp["must"]) or any(re.search(p, s, re.I) for p in sp["not"]):
        return None
    return sum(1 for p in sp["prefer"] if re.search(p, s, re.I)) - len(f["name"]) / 1000


def fetch(sp):
    """[[date, value]] for one series: by ID on each route, else by name on the route's series list."""
    if FIXTURE:
        p = Path(FIXTURE) / f"{sp['k']}.json"
        return json.loads(p.read_text())["rows"] if p.exists() else []
    for route in sp["routes"]:
        rows = rows_for(route, sp["id"], sp["freq"])
        if rows:
            return rows
    best = None
    for route in sp["routes"]:
        for f in facets(route):
            sc = score(f, sp)
            if sc is not None and (best is None or sc > best[0]):
                best = (sc, route, f["id"])
    if best:
        log(f"  {sp['k']}: {sp['id']} not found, using {best[2]} (matched by name)")
        return rows_for(best[1], best[2], sp["freq"])
    return []


SER = {}


def S(k):
    r = SER.get(k) or []
    if not r:
        return pd.Series(dtype=float, index=pd.DatetimeIndex([]))
    s = pd.Series({pd.Timestamp(d): v for d, v in r}, dtype=float).sort_index()
    return s[~s.index.duplicated()]


# ---------------- analysis (from the source model) ----------------
def wk(s, how="mean"):
    """Weekly on Friday (EIA weeks end Friday)."""
    if s.empty:
        return pd.Series(dtype=float, index=pd.DatetimeIndex([]))
    return getattr(s.resample("W-FRI"), how)().dropna()


def vs5(s):
    """Each week's value vs the average of the same ISO week in the previous 5 years."""
    df = pd.DataFrame({"v": s})
    df["y"], df["w"] = df.index.isocalendar().year.values, np.minimum(df.index.isocalendar().week.values, 52)
    piv = df.pivot_table(index="w", columns="y", values="v", aggfunc="last")
    avg = []
    for d, r in df.iterrows():
        prev = [piv.at[r.w, y] for y in range(int(r.y) - 5, int(r.y)) if y in piv.columns and not pd.isna(piv.at[r.w, y])]
        avg.append(np.mean(prev) if len(prev) >= 3 else np.nan)
    df["avg5"] = avg
    df["dev"] = df.v - df.avg5
    df["dev_pct"] = 100 * df.dev / df.avg5
    return df


def seasonal_chart(s, digits=1):
    df = pd.DataFrame({"v": s})
    df["y"], df["w"] = df.index.isocalendar().year.values, np.minimum(df.index.isocalendar().week.values, 52)
    piv = df.pivot_table(index="w", columns="y", values="v", aggfunc="last").reindex(range(1, 53))
    cy = int(df.y.iloc[-1])
    prev = [y for y in piv.columns if cy - 5 <= y < cy]
    r = lambda a: [None if pd.isna(x) else round(float(x), digits) for x in a]
    return {"weeks": list(range(1, 53)), "cy": cy, "this": r(piv.get(cy, pd.Series(index=piv.index))), "last": r(piv.get(cy - 1, pd.Series(index=piv.index))),
            "min5": r(piv[prev].min(axis=1)), "max5": r(piv[prev].max(axis=1)), "avg5": r(piv[prev].mean(axis=1))}


def ols(y, X):
    A = np.column_stack([np.ones(len(X)), X])
    b, *_ = np.linalg.lstsq(A, y, rcond=None)
    fit = A @ b
    ss = ((y - y.mean()) ** 2).sum()
    return b, fit, (1 - ((y - fit) ** 2).sum() / ss) if ss > 0 else None


def season(idx):
    w = 2 * math.pi * idx.dayofyear.values / 365.25
    return np.column_stack([np.sin(w), np.cos(w)])


def model(df, ycol, xcols, log=False, seasonal=True, window=260, horizon=4, label="", unit="", driver_label=""):
    """Rolling-window OLS fair value with a walk-forward test of the gap."""
    d = df[[ycol] + xcols].dropna()
    if len(d) < 160 or d.index[-1] < df.index[-1] - pd.Timedelta(days=21):
        return None   # too little history, or the price series has stopped (a stale fit would mislead)
    y = np.log(d[ycol].values) if log else d[ycol].values
    X = d[xcols].values
    if seasonal:
        X = np.column_stack([X, season(d.index)])
    n = len(d)
    w0 = max(0, n - window)
    b, fit, r2 = ols(y[w0:], X[w0:])
    fv = np.exp(fit) if log else fit
    act = d[ycol].values[w0:]
    resid_now = float(act[-1] - fv[-1])
    sd = float(np.std(act - fv))
    gaps, fwd = [], []
    for t in range(max(window // 2, n - 156), n - horizon):
        a = max(0, t - window)
        bb, _, _ = ols(y[a:t], X[a:t])
        pred = np.r_[1, X[t]] @ bb
        gaps.append(d[ycol].values[t] - (math.exp(pred) if log else pred))
        fwd.append(d[ycol].values[t + horizon] - d[ycol].values[t])
    gaps, fwd = np.array(gaps), np.array(fwd)
    wf = None
    if len(gaps) > 30:
        c = float(np.corrcoef(gaps, fwd)[0, 1])
        hit = float(np.mean(np.sign(-gaps[np.abs(gaps) > 0]) == np.sign(fwd[np.abs(gaps) > 0])))
        wf = {"n": int(len(gaps)), "corr_gap_next": round(c, 2), "hit": round(100 * hit), "horizon_weeks": horizon,
              "reads": "the gap has tended to close" if c < -0.15 and hit > 0.55 else "the gap has not reliably closed (treat as context, not a signal)"}
    return {"label": label, "unit": unit, "driver": driver_label, "log": log, "seasonal": seasonal, "r2": None if r2 is None else round(float(r2), 2),
            "coef": {xcols[i]: round(float(b[i + 1]), 4) for i in range(len(xcols))},
            "window_weeks": int(len(act)), "since": str(d.index[w0].date()), "date": str(d.index[-1].date()),
            "actual": round(float(act[-1]), 3), "fair": round(float(fv[-1]), 3), "gap": round(resid_now, 3), "gap_z": round(resid_now / sd, 2) if sd else None,
            "walk_forward": wf, "x_now": {k: round(float(d[k].iloc[-1]), 2) for k in xcols},
            "series": [[str(i.date()), round(float(a), 3), round(float(f), 3)] for i, a, f in zip(d.index[w0:], act, fv)][-260:],
            "scatter": [[round(float(x), 2), round(float(v), 3)] for x, v in zip(d[xcols[0]].values[w0:], act)]}


def balance(rows, months=False):
    """{label: series} -> latest periods with 4-week / 12-month averages against a year ago."""
    rows = {k: v for k, v in rows.items() if v is not None and len(v)}
    df = pd.DataFrame(rows).sort_index().dropna(how="all")
    df = df[df.index >= df.index.max() - pd.Timedelta(days=800)]
    if df.empty:
        return None
    n_avg = 12 if months else 4
    last = df.tail(8 if not months else 13)
    tbl = {"periods": [str(i.date()) for i in last.index], "rows": [], "avg_label": "12-month average" if months else "4-week average"}
    for c in df.columns:
        s = df[c].dropna()
        if s.empty:
            continue
        avg = s.tail(n_avg).mean()
        ya = s[(s.index <= s.index[-1] - pd.Timedelta(days=364))].tail(n_avg).mean() if len(s) > (n_avg + 12 if months else 60) else np.nan
        tbl["rows"].append({"name": c, "values": [None if pd.isna(last.at[i, c]) else round(float(last.at[i, c]), 1) for i in last.index],
                            "avg": round(float(avg), 1), "avg_ya": None if pd.isna(ya) else round(float(ya), 1),
                            "chg_ya_pct": None if pd.isna(ya) or ya <= 0 or avg <= 0 else round(100 * (avg / ya - 1), 1)})
    return tbl


def tail(s, days=3 * 366, digits=2):
    if not len(s):
        return []
    s = s[s.index >= s.index.max() - pd.Timedelta(days=days)]
    return [[str(i.date()), round(float(v), digits)] for i, v in s.items()]


# ---------------- desk sections ----------------
def gas():
    st = wk(S("storL48"), "last")
    if st.empty:
        raise RuntimeError("no Lower 48 storage")
    g = vs5(st)
    ng = wk(S("hhSpot"))
    g["price"] = ng.reindex(g.index, method="nearest", tolerance=pd.Timedelta(days=3))
    g["dev_pct_x"] = g.dev_pct
    m = model(g, "price", ["dev_pct_x"], log=True, label="Henry Hub spot price (weekly average)", unit="$/MMBtu",
              driver_label="Lower 48 storage vs 5-year average (%)")
    last = g.iloc[-1]
    df = pd.DataFrame({"v": st})
    df["y"] = df.index.isocalendar().year.values
    df["w"] = np.minimum(df.index.isocalendar().week.values, 52)
    piv = df.pivot_table(index="w", columns="y", values="v", aggfunc="last")
    wnow, cy = int(last.w), int(last.y)
    prev = [y for y in piv.columns if cy - 5 <= y < cy]

    def proj(target_w, year_shift=0):
        chg = []
        for y in prev:
            a = piv.at[wnow, y] if wnow in piv.index else np.nan
            b = piv.at[target_w, y + year_shift] if (y + year_shift) in piv.columns and target_w in piv.index else np.nan
            if not pd.isna(a) and not pd.isna(b):
                chg.append(b - a)
        avg = [piv.at[target_w, y + year_shift] for y in prev if (y + year_shift) in piv.columns and not pd.isna(piv.at[target_w, y + year_shift])]
        return (float(last.v + np.mean(chg)) if chg else None), (float(np.mean(avg)) if avg else None)

    proj_rows = []
    if wnow <= 44:
        p, a = proj(44)
        proj_rows.append({"what": "end of October (injection season end)", "projected": round(p) if p else None, "avg5": round(a) if a else None})
    p, a = proj(13, 1 if wnow > 13 else 0)
    proj_rows.append({"what": "end of March (withdrawal season end)", "projected": round(p) if p else None, "avg5": round(a) if a else None})
    dpm = lambda s: (s / s.index.days_in_month / 1000) if not s.empty else s
    bal = balance({"Dry production": dpm(S("prodDry")), "Imports": dpm(S("impTot")), "Residential": dpm(S("consRes")), "Commercial": dpm(S("consCom")),
                   "Industrial": dpm(S("consInd")), "Power": dpm(S("consPow")), "Total consumption": dpm(S("consTot")), "LNG exports": dpm(S("expLng")),
                   "Total exports": dpm(S("expTot"))}, months=True)
    # weekly net change against the 5-year average change, and the surplus/deficit path
    ch = g.v.diff()
    avgch = g.avg5.diff()
    weekly = [[str(i.date()), round(float(a), 0), None if pd.isna(b) else round(float(b), 0)] for i, a, b in zip(g.index[-26:], ch.iloc[-26:], avgch.iloc[-26:])]
    surplus = [[str(i.date()), round(float(d), 0), round(float(p), 1)] for i, d, p in zip(g.index[-260:], g.dev.iloc[-260:], g.dev_pct.iloc[-260:]) if not pd.isna(d)]
    regions = []
    for k, name in (("storEast", "East"), ("storMw", "Midwest"), ("storSc", "South Central"), ("storScSalt", "South Central: salt"), ("storScNon", "South Central: non-salt"),
                    ("storMtn", "Mountain"), ("storPac", "Pacific")):
        s = wk(S(k), "last")
        if s.empty:
            continue
        r = vs5(s).iloc[-1]
        regions.append({"name": name, "value": round(float(r.v)), "wow": round(float(s.diff().iloc[-1])), "avg5": None if pd.isna(r.avg5) else round(float(r.avg5)),
                        "dev_pct": None if pd.isna(r.dev_pct) else round(float(r.dev_pct), 1), "yago": round(float(s.iloc[-53])) if len(s) > 53 else None})
    steo = {k: tail(S(k).resample("MS").last(), days=4 * 366, digits=2) for k in ("steoProd", "steoCons", "steoLng", "steoStor", "steoHdd", "steoCdd")}
    return {"name": "Natural gas", "unit_stock": "Bcf",
            "stocks": {"name": "Lower 48 working gas", "date": str(g.index[-1].date()), "value": round(float(last.v)), "avg5": round(float(last.avg5)),
                       "dev": round(float(last.dev)), "dev_pct": round(float(last.dev_pct), 1), "wow": round(float(g.v.diff().iloc[-1])),
                       "wow_avg5": None if pd.isna(avgch.iloc[-1]) else round(float(avgch.iloc[-1])), "yago": round(float(g.v.iloc[-53])) if len(g) > 53 else None},
            "seasonal": seasonal_chart(st, 0), "weekly_change": weekly, "surplus": surplus, "regions": regions,
            "projection": proj_rows, "balance": bal, "balance_unit": "Bcf/d (EIA monthly)", "fair": m, "steo": steo,
            "prices": {"hh": tail(S("hhSpot"))}}


def crude():
    cr = wk(S("crude"), "last") / 1000
    if cr.empty:
        raise RuntimeError("no crude stocks")
    c = vs5(cr)
    cu_s = wk(S("cushing"), "last") / 1000
    cu = vs5(cu_s) if not cu_s.empty else None
    runs = wk(S("runs"))
    c["days"] = c.v * 1000 / runs.reindex(c.index, method="nearest", tolerance=pd.Timedelta(days=3))
    c["days_dev"] = vs5(c["days"].dropna()).dev
    m = None   # WTI 1st-2nd month spread model: needs NYMEX futures, which EIA no longer publishes (see the module note)
    c["wti"] = wk(S("wti")).reindex(c.index, method="nearest", tolerance=pd.Timedelta(days=3))
    m2 = model(c, "wti", ["days_dev"], log=True, seasonal=False, label="WTI spot (outright)")
    if m2:
        m2 = {k: m2[k] for k in ("label", "r2", "window_weeks", "since")}   # shown only to make the point that U.S. stocks explain little of the outright price
    dstock = cr.diff() * 1000 / 7
    bal = balance({"Production": wk(S("prod")), "Imports": wk(S("imp")), "Exports": wk(S("exp")), "Refinery crude input": wk(S("runs")),
                   "Change in commercial stocks": dstock, "Adjustment (balancing item)": dstock - (wk(S("prod")) + wk(S("imp")) - wk(S("exp")) - wk(S("runs")))})
    last = c.iloc[-1]
    builds = [[str(i.date()), round(float(a), 1), None if pd.isna(b) else round(float(b), 1)] for i, a, b in zip(c.index[-26:], c.v.diff().iloc[-26:], c.avg5.diff().iloc[-26:])]
    wb = (S("wti") - S("brent")).dropna()
    return {"name": "WTI crude", "unit_stock": "million bbl",
            "stocks": {"name": "U.S. commercial crude stocks (ex-SPR)", "date": str(c.index[-1].date()), "value": round(float(last.v), 1), "avg5": round(float(last.avg5), 1),
                       "dev": round(float(last.dev), 1), "dev_pct": round(float(last.dev_pct), 1), "wow": round(float(c.v.diff().iloc[-1]), 1),
                       "days": round(float(last.days), 1) if not pd.isna(last.days) else None,
                       "cushing": round(float(cu.v.iloc[-1]), 1) if cu is not None else None, "cushing_avg5": round(float(cu.avg5.iloc[-1]), 1) if cu is not None else None,
                       "cushing_wow": round(float(cu.v.diff().iloc[-1]), 1) if cu is not None else None,
                       "spr": round(float(wk(S("spr"), "last").iloc[-1]) / 1000, 1) if not S("spr").empty else None},
            "seasonal": seasonal_chart(cr), "seasonal_cushing": seasonal_chart(cu_s) if not cu_s.empty else None, "builds": builds,
            "balance": bal, "balance_unit": "thousand b/d (EIA weekly)", "fair": m, "fair_outright": m2,
            "refining": {"runs": tail(wk(S("runs")), digits=0), "util": tail(wk(S("util")), digits=1)},
            "prices": {"wti": tail(S("wti")), "brent": tail(S("brent")), "wti_brent": tail(wb)}}


def product(sym, nm, stk, dem, prod, imp, exp, spot):
    s = wk(S(stk), "last") / 1000
    if s.empty:
        raise RuntimeError(f"no {stk} stocks")
    p = vs5(s)
    demand = wk(S(dem)).rolling(4, min_periods=2).mean()
    p["days"] = p.v * 1000 / demand.reindex(p.index, method="nearest", tolerance=pd.Timedelta(days=3))
    p["days_dev"] = vs5(p["days"].dropna()).dev
    crack = (wk(S(spot)) * 42 - wk(S("wti"))).dropna()
    p["crack"] = crack.reindex(p.index, method="nearest", tolerance=pd.Timedelta(days=3))
    short = nm.split(" / ")[1]
    m = model(p, "crack", ["days_dev"], label=f"Gulf Coast {short} crack vs WTI", unit="$/bbl", driver_label="days of supply vs 5-year average")
    dstock = s.diff() * 1000 / 7
    bal = balance({"Refinery production": wk(S(prod)), "Imports": wk(S(imp)), "Exports": wk(S(exp)), "Product supplied (demand)": wk(S(dem)), "Change in stocks": dstock})
    last = p.iloc[-1]
    daily_crack = (S(spot) * 42 - S("wti")).dropna()
    return {"name": nm, "unit_stock": "million bbl",
            "stocks": {"name": f"U.S. {short} stocks", "date": str(p.index[-1].date()), "value": round(float(last.v), 1), "avg5": round(float(last.avg5), 1),
                       "dev": round(float(last.dev), 1), "dev_pct": round(float(last.dev_pct), 1), "wow": round(float(p.v.diff().iloc[-1]), 1),
                       "days": round(float(last.days), 1) if not pd.isna(last.days) else None,
                       "days_avg5": round(float(last.days - last.days_dev), 1) if not pd.isna(last.days_dev) else None},
            "seasonal": seasonal_chart(s), "balance": bal, "balance_unit": "thousand b/d (EIA weekly)", "fair": m,
            "demand": tail(wk(S(dem)).rolling(4, min_periods=2).mean(), digits=0),
            "crack": tail(daily_crack), "crack_seasonal": seasonal_chart(wk(daily_crack), 2) if len(daily_crack) > 400 else None}


def futures_curves():
    """WTI and Henry Hub futures curves written earlier in the build by pipelines/prices (Yahoo), if present."""
    p = Path(os.environ.get("PRICES_DIR") or Path(__file__).resolve().parents[2] / ".work" / "prices") / "curves.json"
    try:
        return json.loads(p.read_text()).get("curves", {})
    except Exception:
        return {}


def quality(f):
    r2, wf = f.get("r2") or 0, (f.get("walk_forward") or {})
    return ("usable: inventories explain much of the price and gaps have closed" if r2 >= 0.5 and wf.get("corr_gap_next", 0) < -0.15 else
            "partial: inventories explain part of the price" if r2 >= 0.25 else
            "weak: inventories explain little of this price right now (global and refinery factors dominate); shown for context")


def read(M):
    st, f = M["stocks"], M.get("fair")
    t = [f"{st['name']} {st['value']:,} {M['unit_stock']} (week to {st['date']}), {st['dev']:+,} ({st['dev_pct']:+.1f}%) vs the 5-year average, {st['wow']:+,} on the week"
         + (f"; {st['days']} days of supply" if st.get("days") else "") + "."]
    if f:
        t.append(f"Inventory fair value for the {f['label']}: {f['fair']:.2f} {f['unit']} vs {f['actual']:.2f} actual (gap {f['gap']:+.2f}, z {f['gap_z']:+.1f}; "
                 f"R² {f['r2']} over {f['window_weeks']} weeks; model {f['quality'].split(':')[0]})"
                 + (f"; walk-forward: {f['walk_forward']['reads']} (corr {f['walk_forward']['corr_gap_next']}, hit {f['walk_forward']['hit']}% over "
                    f"{f['walk_forward']['horizon_weeks']} weeks)." if f.get("walk_forward") else "."))
    if M.get("projection"):
        t.append("At the 5-year average pace from here: " + "; ".join(f"{x['what']} {x['projected']:,} Bcf (5-yr avg {x['avg5']:,})" for x in M["projection"] if x["projected"]) + ".")
    return " ".join(t)


def clean(o):
    if isinstance(o, dict):
        return {k: clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, (float, np.floating)):
        return float(o) if np.isfinite(o) else None
    if isinstance(o, np.integer):
        return int(o)
    return o


def main():
    if not KEY and not FIXTURE:
        raise SystemExit("EIA_API_KEY is not set")
    missing = []
    for sp in SPECS:
        try:
            rows = fetch(sp)
        except RuntimeError as e:
            raise SystemExit(str(e))
        if sp["freq"] == "daily" and rows:
            rows = [r for r in rows if r[0] >= f"{NOW.year - 8}-01-01"]
        SER[sp["k"]] = rows
        if not rows:
            missing.append(sp["k"])
        if not FIXTURE:
            time.sleep(0.3)
    markets, errors = {}, []
    for sym, fn in (("NG", gas), ("CL", crude),
                    ("HO", lambda: product("HO", "ULSD / distillate", "dist", "demDist", "distProd", "distImp", "distExp", "spotDist")),
                    ("RB", lambda: product("RB", "RBOB / gasoline", "gaso", "demGaso", "gasoProd", "gasoImp", "gasoExp", "spotGaso"))):
        try:
            M = fn()
            if M.get("fair"):
                M["fair"]["quality"] = quality(M["fair"])
            M["read"] = read(M)
            markets[sym] = M
            log(sym, "ok", M["stocks"]["date"])
        except Exception as e:
            errors.append(f"{sym} ({str(e)[:80]})")
            log(sym, "FAILED", e)
    if not markets:
        raise SystemExit("every energy market failed: " + "; ".join(errors))
    cv = futures_curves()
    for sym in ("NG", "CL"):
        if sym in markets and cv.get(sym):
            markets[sym]["curve"] = cv[sym]
    freshness = [{"k": sp["k"], "label": sp["label"], "freq": sp["freq"], "last": SER[sp["k"]][-1][0] if SER[sp["k"]] else None} for sp in SPECS]
    dates = [M["stocks"]["date"] for M in markets.values()]
    note = "; ".join(errors + ([f"EIA series not found: {', '.join(missing)}"] if missing else []))
    print(json.dumps(clean({"data": {"markets": markets, "freshness": freshness}, "latest": max(dates), "n": len(markets),
                            "src": "U.S. Energy Information Administration (Open Data v2)", "note": note, "partial": bool(errors or missing)}),
                     separators=(",", ":"), allow_nan=False, default=str))


if __name__ == "__main__":
    main()
